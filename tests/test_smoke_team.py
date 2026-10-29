# [PATCH:STAGE8-test-smoke]
"""Full team-mode flow + local-mode no-auth sanity check."""
import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def team_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "team.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


@pytest.fixture
def local_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "local.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


def test_team_full_flow(team_client):
    c = team_client
    assert c.get("/api/auth/status").json()["needs_setup"] is True

    r = c.post("/api/setup/admin",
               json={"username": "admin", "password": "admin12345678"})
    assert r.status_code == 200

    r = c.post("/api/users",
               json={"username": "ann", "password": "ann12345678",
                     "role": "annotator"})
    assert r.status_code == 200

    c.post("/api/auth/logout")
    r = c.post("/api/auth/login",
               json={"username": "ann", "password": "ann12345678"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "annotator"

    # Annotator не может создавать юзеров
    r = c.post("/api/users",
               json={"username": "x", "password": "x12345678",
                     "role": "annotator"})
    assert r.status_code == 403

    c.post("/api/auth/logout")


def test_local_mode_no_login(local_client):
    c = local_client
    r = c.get("/api/auth/status")
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "local"
    assert d["is_authenticated"] is True

    # Обычный запрос проходит без cookie
    r = c.get("/api/projects")
    assert r.status_code == 200
