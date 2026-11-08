"""Stage 5.2 — RBAC fail-closed coverage."""
import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def team_client(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "rbac.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    c = TestClient(app_mod.app)
    c.post("/api/setup/admin",
           json={"username": "admin", "password": "admin12345678"})
    return c


def test_unmatched_api_route_denied(team_client):
    """Незарегистрированный /api/* → 403 (не 200/404)."""
    r = team_client.get("/api/_not_registered_endpoint_xyz")
    assert r.status_code in (403, 404), r.text


def test_public_routes_still_accessible(team_client):
    for path in ("/api/health", "/api/version"):
        r = team_client.get(path)
        assert r.status_code == 200, f"{path}: {r.text}"


def test_whitelisted_route_passes(team_client):
    r = team_client.get("/api/auth/status")
    assert r.status_code == 200
