"""[STAGE6:test-api-v2] Bearer-авторизация в team mode без cookie."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def team_client(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "v2.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("API_KEY", "test_key_123")
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    client = TestClient(app_mod.app)
    client.post("/api/setup/admin",
                json={"username": "admin", "password": "admin12345678"})
    return client


def test_v2_requires_bearer(team_client):
    r = team_client.get("/api/v2/projects")
    assert r.status_code == 401


def test_v2_with_valid_bearer(team_client):
    r = team_client.get("/api/v2/projects",
                        headers={"Authorization": "Bearer test_key_123"})
    assert r.status_code == 200


def test_v2_works_without_cookie(team_client):
    """Главный фикс C4: /api/v2/* не должен требовать cookie в team mode."""
    team_client.post("/api/auth/logout")
    r = team_client.get("/api/v2/projects",
                        headers={"Authorization": "Bearer test_key_123"})
    assert r.status_code == 200


def test_v2_wrong_bearer(team_client):
    r = team_client.get("/api/v2/projects",
                        headers={"Authorization": "Bearer wrong_key"})
    assert r.status_code in (401, 403)
# [STAGE6:test-fixes]
