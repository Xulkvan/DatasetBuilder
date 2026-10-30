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
    # [STAGE6:test-fixes-2-imports] Кроссплатформенно: временная папка
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
