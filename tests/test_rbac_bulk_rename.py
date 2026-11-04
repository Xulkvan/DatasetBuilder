"""[PATCH:STAGE1-C24] Annotator cannot bulk_rename."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def team_client(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "rbacbr.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    c = TestClient(app_mod.app)
    c.post("/api/setup/admin",
           json={"username": "admin", "password": "admin12345678"})
    r = c.post("/api/users", json={
        "username": "ann", "password": "ann12345678", "role": "annotator"})
    assert r.status_code == 200, r.text
    return c


def test_annotator_cannot_bulk_rename(team_client):
    team_client.post("/api/auth/logout")
    team_client.post("/api/auth/login",
                     json={"username": "ann", "password": "ann12345678"})
    r = team_client.post("/api/images/bulk_rename", json={
        "image_ids": [1, 2], "pattern": "x_{n}", "start": 1})
    assert r.status_code == 403, r.text


def test_manager_can_bulk_rename(team_client):
    # manager имеет image.delete
    team_client.post("/api/users", json={
        "username": "mgr", "password": "mgr12345678", "role": "manager"})
    team_client.post("/api/auth/logout")
    team_client.post("/api/auth/login",
                     json={"username": "mgr", "password": "mgr12345678"})
    # Пустой payload -> 400/422, но НЕ 403
    r = team_client.post("/api/images/bulk_rename", json={
        "image_ids": [], "pattern": "x_{n}", "start": 1})
    assert r.status_code != 403, r.text
