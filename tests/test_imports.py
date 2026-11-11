"""[STAGE6:test-imports] Импорт из локальной папки ограничен."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def local_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "imp.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import app as app_mod
    importlib.reload(app_mod)
    client = TestClient(app_mod.app)
    r = client.post("/api/projects",
                    data={"name": "imp", "object_class": "pig"})
    return client, r.json()["id"]


def test_outside_data_root_blocked(local_client):
    # Кроссплатформенно: временная папка
    # вне DATA_ROOT. На Windows /etc и /proc не существуют —
    # os.path.isabs() возвращает False → 400 вместо 403.
    import tempfile, shutil
    outside = tempfile.mkdtemp(prefix="outside_data_root_")
    try:
        client, pid = local_client
        r = client.post(f"/api/projects/{pid}/import/local_folder",
                        json={"path": outside, "recursive": False})
        assert r.status_code == 403, \
            f"expected 403, got {r.status_code}: {r.text[:200]}"
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def test_relative_path_rejected(local_client):
    # Относительный путь → 400 (валидация до проверки DATA_ROOT)
    client, pid = local_client
    r = client.post(f"/api/projects/{pid}/import/local_folder",
                    json={"path": "relative/path", "recursive": False})
    assert r.status_code == 400


# Stage 5.7 — symlink in local folder import
def test_symlink_in_local_folder_blocked(monkeypatch, tmp_path, clean_auth_db):
    import importlib
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sym.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    c = TestClient(app_mod.app)
    r = c.post("/api/projects", data={"name": "sym", "object_class": "pig"})
    pid = r.json()["id"]

    from config import IMPORT_DIR
    import os
    base = os.path.join(IMPORT_DIR, "symlink_test")
    os.makedirs(base, exist_ok=True)
    target = os.path.join(base, "real.jpg")
    with open(target, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0" + b"x" * 100)
    link = os.path.join(base, "link.jpg")
    try:
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        import pytest
        pytest.skip("symlink not supported")

    try:
        r = c.post(f"/api/projects/{pid}/import/local_folder",
                   json={"path": base, "recursive": False})
        # Либо 200 с skip symlink, либо 400/403 — но не 500
        assert r.status_code != 500, r.text
    finally:
        try:
            os.unlink(link)
        except OSError:
            pass
        try:
            os.unlink(target)
        except OSError:
            pass
        try:
            os.rmdir(base)
        except OSError:
            pass
