"""[PATCH:STAGE5-T3] C3: v2 export download по Bearer без cookie."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def team_client(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t3.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("API_KEY", "test_key_123")
    monkeypatch.setenv("CSRF_STRICT", "0")
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    c = TestClient(app_mod.app)
    c.post("/api/setup/admin",
           json={"username": "admin", "password": "admin12345678"})
    return c


class TestV2ExportBearer:
    def test_v2_export_download_with_bearer(self, team_client):
        r = team_client.post("/api/projects",
                             data={"name": "t3_p", "object_class": "pig"})
        assert r.status_code == 200
        pid = r.json()["id"]
        r = team_client.get(
            f"/api/v2/projects/{pid}/export/yolo/download",
            headers={"Authorization": "Bearer test_key_123"},
        )
        # 200 / 404 (нет images) / 500 — но НЕ 401/403
        assert r.status_code not in (401, 403), r.text

    def test_v2_export_download_without_bearer(self, team_client):
        r = team_client.post("/api/projects",
                             data={"name": "t3_p2", "object_class": "pig"})
        pid = r.json()["id"]
        r = team_client.get(f"/api/v2/projects/{pid}/export/yolo/download")
        assert r.status_code in (401, 403), r.text

    def test_v2_export_works_without_cookie(self, team_client):
        r = team_client.post("/api/projects",
                             data={"name": "t3_p3", "object_class": "pig"})
        pid = r.json()["id"]
        team_client.cookies.clear()
        r = team_client.get(
            f"/api/v2/projects/{pid}/export/coco/download",
            headers={"Authorization": "Bearer test_key_123"},
        )
        assert r.status_code not in (401, 403), r.text
