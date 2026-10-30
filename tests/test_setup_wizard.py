"""[STAGE6:test-setup-wizard] Setup admin via JSON body."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def team_client(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sw.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


def test_setup_admin_json(team_client):
    r = team_client.post("/api/setup/admin",
                         json={"username": "admin", "password": "abcdef1234"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "admin"


def test_setup_admin_formdata_rejected(team_client):
    """Fallback-баг C5: FormData на JSON-эндпоинт → 422."""
    r = team_client.post("/api/setup/admin",
                         data={"username": "admin", "password": "abcdef1234"})
    assert r.status_code == 422


def test_setup_status_needs_setup(team_client):
    r = team_client.get("/api/setup/status")
    assert r.status_code == 200
    assert r.json()["needs_setup"] is True
# [STAGE6:test-fixes]
