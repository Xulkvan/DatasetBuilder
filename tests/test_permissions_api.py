"""[STAGE6:permissions-api] Матрица прав приходит с сервера.

Проверяет:
  * /api/auth/status возвращает permissions;
  * /api/auth/me возвращает permissions;
  * /api/permissions — новый эндпоинт;
  * local mode = все permissions;
  * annotator не видит admin-прав;
  * содержимое совпадает с config.ROLE_PERMISSIONS.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from config import ROLE_PERMISSIONS, ROLE_ADMIN, ROLE_ANNOTATOR


@pytest.fixture
def local_client(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "p_local.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


@pytest.fixture
def team_client(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "p_team.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import app as app_mod
    importlib.reload(app_mod)
    client = TestClient(app_mod.app)
    client.post("/api/setup/admin",
                json={"username": "admin", "password": "admin12345678"})
    return client


def test_local_status_has_all_permissions(local_client):
    r = local_client.get("/api/auth/status")
    assert r.status_code == 200
    d = r.json()
    assert "permissions" in d
    perms = set(d["permissions"])
    # local = union всех ролей
    expected = set()
    for p in ROLE_PERMISSIONS.values():
        expected.update(p)
    assert perms == expected


def test_team_status_admin_permissions(team_client):
    r = team_client.get("/api/auth/status")
    d = r.json()
    assert d["is_authenticated"] is True
    assert set(d["permissions"]) == ROLE_PERMISSIONS[ROLE_ADMIN]


def test_permissions_endpoint_admin(team_client):
    r = team_client.get("/api/permissions")
    if r.status_code != 200:
        # [STAGE6:test-fixes-2-debug] диагностика
        print(f"\n[DEBUG] /api/permissions -> {r.status_code} {r.text[:300]}")
        _st = team_client.get("/api/auth/status")
        print(f"[DEBUG] /api/auth/status -> {_st.status_code} {_st.json()}")
        print(f"[DEBUG] cookies -> {dict(team_client.cookies)}")
    assert r.status_code == 200
    d = r.json()
    assert d["role"] == "admin"
    assert set(d["permissions"]) == ROLE_PERMISSIONS[ROLE_ADMIN]


def test_permissions_endpoint_annotator(team_client):
    team_client.post("/api/users",
                     json={"username": "ann", "password": "ann12345678",
                           "role": "annotator"})
    team_client.post("/api/auth/logout")
    team_client.post("/api/auth/login",
                     json={"username": "ann", "password": "ann12345678"})
    r = team_client.get("/api/permissions")
    d = r.json()
    assert d["role"] == "annotator"
    assert set(d["permissions"]) == ROLE_PERMISSIONS[ROLE_ANNOTATOR]
    assert "user.manage" not in d["permissions"]
    assert "annotation.write" in d["permissions"]


def test_auth_me_includes_permissions(team_client):
    r = team_client.get("/api/auth/me")
    assert r.status_code == 200
    d = r.json()
    assert "permissions" in d
    assert isinstance(d["permissions"], list)
    assert set(d["permissions"]) == ROLE_PERMISSIONS[ROLE_ADMIN]


def test_login_response_includes_permissions(team_client):
    team_client.post("/api/auth/logout")
    r = team_client.post("/api/auth/login",
                         json={"username": "admin",
                               "password": "admin12345678"})
    assert r.status_code == 200
    d = r.json()
    assert "permissions" in d
    assert set(d["permissions"]) == ROLE_PERMISSIONS[ROLE_ADMIN]


def test_setup_admin_response_includes_permissions(monkeypatch, tmp_path, clean_auth_db):  # [STAGE6:test-fixes-5-setup-admin]
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "p_setup.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    client = TestClient(app_mod.app)
    r = client.post("/api/setup/admin",
                    json={"username": "root", "password": "root12345678"})
    assert r.status_code == 200
    d = r.json()
    assert "permissions" in d
    assert "user.manage" in d["permissions"]
# [STAGE6:test-fixes]
