"""[STAGE-2-PATCH-V3] Import robustness (2.3): corrupt images, no magic, sanitize.

Покрывает:
  * corrupt image в zip -> failed_images >= 1, импорт продолжается
  * отсутствие magic bytes -> skip
  * filename sanitize 1.9: ..
  * rate-limiter сбрасывается между тестами (autouse)
  * _fresh_project: изоляция pHash-дубликатов и project state

ВАЖНО: каждый тест использует СВЕЖИЙ проект (POST /api/projects).
Иначе good.jpg импортируется в первом тесте, а во втором ловится
как pHash-дубликат -> imported_images = 0.
"""
import importlib
import io
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def local_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "imp.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


@pytest.fixture(autouse=True)
def _reset_import_limiter():
    """Глобальный _limiter_import: 5 за 600с. Сбрасываем перед каждым тестом."""
    try:
        from services.rate_limiter import _limiter_import
        with _limiter_import._lock:
            _limiter_import._buckets.clear()
    except Exception:
        pass
    yield


def _fresh_project(client):
    """Свежий проект -- изоляция pHash-дубликатов и counters."""
    r = client.post(
        "/api/projects",
        data={"name": "imp_" + uuid.uuid4().hex[:8], "object_class": "pig"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _make_jpeg(color: tuple = (100, 100, 100)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="JPEG")
    return buf.getvalue()


def _upload_zip(client, pid, zip_path):
    with open(zip_path, "rb") as f:
        return client.post(
            f"/api/projects/{pid}/import",
            files={"file": ("test.zip", f, "application/zip")},
        )


# ===========================================================================
# Corrupt images
# ===========================================================================

def test_corrupt_image_in_zip_does_not_abort_import(local_client, tmp_path):
    """Битая картинка -> failed_images >= 1, импорт продолжается."""
    pid = _fresh_project(local_client)
    zpath = tmp_path / "mixed.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("good.jpg", _make_jpeg(color=(100, 100, 100)))
        z.writestr("bad.jpg", b"\xff\xd8\xff" + b"garbage" * 100)

    r = _upload_zip(local_client, pid, zpath)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["imported_images"] >= 1, f"response: {data}"
    assert data["failed_images"] >= 1, f"response: {data}"


def test_no_magic_bytes_skipped(local_client, tmp_path):
    """Файл с расширением .jpg без magic bytes -> failed_images."""
    pid = _fresh_project(local_client)
    zpath = tmp_path / "nomagic.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("fake.jpg", b"not-a-real-image-at-all" * 10)

    r = _upload_zip(local_client, pid, zpath)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["failed_images"] >= 1, f"response: {data}"
    assert data["imported_images"] == 0, f"response: {data}"


# ===========================================================================
# Filename sanitization (1.9)
# ===========================================================================

def test_double_dot_in_filename_skipped(local_client, tmp_path):
    """1.9: .. в имени (не сегмент) -> _is_simple_filename=False -> skip."""
    pid = _fresh_project(local_client)
    zpath = tmp_path / "dbl.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("foo..bar.jpg", _make_jpeg(color=(150, 150, 150)))

    r = _upload_zip(local_client, pid, zpath)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["failed_images"] >= 1, f"response: {data}"
    assert data["imported_images"] == 0, f"response: {data}"


# ===========================================================================
# Import continues after multiple failures
# ===========================================================================

def test_multiple_failures_do_not_abort(local_client, tmp_path):
    """2 битых + 1 валидный -> imported=1, failed=2, импорт не падает."""
    pid = _fresh_project(local_client)
    zpath = tmp_path / "many_bad.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("bad1.jpg", b"\xff\xd8\xff" + b"x" * 100)
        z.writestr("bad2.jpg", b"not-an-image" * 50)
        z.writestr("good.jpg", _make_jpeg(color=(50, 100, 150)))

    r = _upload_zip(local_client, pid, zpath)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["imported_images"] >= 1, f"response: {data}"
    assert data["failed_images"] >= 2, f"response: {data}"
    # Валидный файл — не дубликат (свежий проект)
    assert data.get("skipped_duplicates", 0) == 0, f"response: {data}"
