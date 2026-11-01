"""Тесты профиля: смена логина, смена пароля, full_name."""
import importlib
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(monkeypatch, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", ":memory:")
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)

def test_profile_update(client):
    client.post("/api/setup/admin", json={"username": "admin", "password": "admin12345678"})

    # 1. Смена логина
    r = client.patch("/api/auth/profile", json={"username": "superadmin"})
    assert r.status_code == 200
    r = client.get("/api/auth/me")
    assert r.json()["username"] == "superadmin"

    # 2. Смена пароля с неверным старым
    r = client.patch("/api/auth/profile", json={"password": "newpass123", "old_password": "wrong"})
    assert r.status_code == 401

    # 3. Смена пароля с верным старым
    r = client.patch("/api/auth/profile", json={"password": "newpass123", "old_password": "admin12345678"})
    assert r.status_code == 200

    # Проверяем вход с новым паролем
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"username": "superadmin", "password": "newpass123"})
    assert r.status_code == 200
