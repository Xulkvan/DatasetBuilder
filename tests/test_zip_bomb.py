"""[STAGE-2-PATCH-V3] Zip-bomb / zip-limits / decompression-bomb tests.

Покрывает:
  * _safe_extract_zip: лимит файлов (1.4) -> 413
  * _safe_extract_zip: suspicious compression ratio (1.4) -> 400
  * _process_dataset_zip: decompression bomb (1.2) -> failed_images >= 1
  * _process_dataset_zip: per-image size limit (1.8) -> failed_images >= 1
  * upload_video: использует _open_image_safe (1.3) -- статическая проверка

ВАЖНО про decompression bomb:
  PIL использует 2 * MAX_IMAGE_PIXELS как error-порог.
  MAX_IMAGE_PIXELS -> Warning, 2*MAX_IMAGE_PIXELS -> DecompressionBombError.
  По умолчанию app.py ставит MAX_IMAGE_PIXELS = 50M => error при >100M px.
  8000x8000 = 64M -> только Warning, не Error.
  Поэтому в тесте monkeypatch-им PILImage.MAX_IMAGE_PIXELS = 1M
  -> error при >2M px -> 64M triggers DecompressionBombError.
"""
import importlib
import io
import inspect
import zipfile

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def local_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zb.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


@pytest.fixture(autouse=True)
def _reset_import_limiter():
    try:
        from services.rate_limiter import _limiter_import
        with _limiter_import._lock:
            _limiter_import._buckets.clear()
    except Exception:
        pass
    yield


def _fresh_project(client):
    """Свежий проект -- изоляция pHash / counters / rate-limiter."""
    import uuid as _uuid
    r = client.post(
        "/api/projects",
        data={"name": "zb_" + _uuid.uuid4().hex[:8], "object_class": "pig"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _make_png_bomb(size: int = 8000) -> bytes:
    """PNG size x size uniform -- tiny file, huge decompressed pixel count."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (size, size), (0, 0, 0)).save(
        buf, format="PNG", optimize=True,
    )
    return buf.getvalue()


def _make_valid_jpeg(w: int = 64, h: int = 64,
                     color: tuple = (100, 100, 100)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG")
    return buf.getvalue()


# ===========================================================================
# _safe_extract_zip
# ===========================================================================

def test_zip_with_too_many_files_rejected(tmp_path):
    """1.4: file-count limit -> 413."""
    from services.zip_import_service import _safe_extract_zip  # [PATCH:RECOMMENDATIONS-TESTS-EXTRACT-IMPORT]
    zpath = tmp_path / "many.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
        for i in range(10500):
            z.writestr(f"f{i}.txt", b"x")
    out = tmp_path / "out"
    out.mkdir()
    with zipfile.ZipFile(zpath) as zf:
        with pytest.raises(HTTPException) as ei:
            _safe_extract_zip(zf, str(out))
    assert ei.value.status_code == 413


def test_zip_with_suspicious_ratio_rejected(tmp_path):
    """1.4: compression ratio > 1000 для файлов > 1MB -> 400."""
    from services.zip_import_service import _safe_extract_zip  # [PATCH:RECOMMENDATIONS-TESTS-EXTRACT-IMPORT]
    zpath = tmp_path / "ratio.zip"
    payload = b"\x00" * (2 * 1024 * 1024)
    try:
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_BZIP2) as z:
            z.writestr("big.bin", payload)
    except (RuntimeError, NotImplementedError):
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_LZMA) as z:
            z.writestr("big.bin", payload)
    out = tmp_path / "out"
    out.mkdir()
    with zipfile.ZipFile(zpath) as zf:
        with pytest.raises(HTTPException) as ei:
            _safe_extract_zip(zf, str(out))
    assert ei.value.status_code == 400


# ===========================================================================
# _process_dataset_zip via endpoint
# ===========================================================================

def test_decompression_bomb_in_zip_fails_gracefully(
        local_client, tmp_path, monkeypatch):
    """1.2: пониженный порог PIL -> DecompressionBombError -> failed_images.

    PIL error-порог = 2 * MAX_IMAGE_PIXELS. По умолчанию 50M -> 100M px.
    8000x8000 = 64M -- только warning. Ставим 1M -> error при >2M px.
    """
    from PIL import Image as _PILImage
    monkeypatch.setattr(_PILImage, "MAX_IMAGE_PIXELS", 1_000_000)

    pid = _fresh_project(local_client)
    bomb = _make_png_bomb(8000)
    assert len(bomb) < 5 * 1024 * 1024, "sanity: PNG должен быть маленьким"

    zpath = tmp_path / "bomb.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bomb.png", bomb)

    with open(zpath, "rb") as f:
        r = local_client.post(
            f"/api/projects/{pid}/import",
            files={"file": ("bomb.zip", f, "application/zip")},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["failed_images"] >= 1, f"response: {data}"
    assert data["imported_images"] == 0, f"response: {data}"


def test_oversized_image_in_zip_skipped(
        local_client, tmp_path, monkeypatch):
    """1.8: per-image MAX_UPLOAD_BYTES -> failed_images."""
    monkeypatch.setattr("config.MAX_UPLOAD_BYTES", 1024)  # [PATCH:RECOMMENDATIONS-TESTS-ZIP-BOMB]

    pid = _fresh_project(local_client)
    large_jpeg = _make_valid_jpeg(512, 512)
    assert len(large_jpeg) > 1024

    zpath = tmp_path / "big.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("big.jpg", large_jpeg)

    with open(zpath, "rb") as f:
        r = local_client.post(
            f"/api/projects/{pid}/import",
            files={"file": ("big.zip", f, "application/zip")},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["failed_images"] >= 1, f"response: {data}"


def test_upload_video_uses_open_image_safe():
    """1.3: upload_video должен использовать _open_image_safe (статическая проверка)."""
    import app as app_mod
    src = inspect.getsource(app_mod.upload_video)
    assert "_open_image_safe" in src, (
        "upload_video не использует _open_image_safe -- fix 1.3 не применён"
    )
    assert "Image.open(fp)" not in src, (
        "upload_video всё ещё использует Image.open(fp) -- fix 1.3 не применён"
    )
