"""Auth: setup, login, session, change password."""
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


def test_setup_first_admin(client):
    r = client.get("/api/auth/status")
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "team"
    assert d["needs_setup"] is True

    r = client.post("/api/setup/admin",
                    json={"username": "admin", "password": "test12345678"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"

    r = client.get("/api/auth/status")
    assert r.json()["needs_setup"] is False


def test_login_wrong_password(client):
    client.post("/api/setup/admin",
                json={"username": "admin", "password": "test12345678"})
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login",
                    json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_login_success_sets_cookie(client):
    client.post("/api/setup/admin",
                json={"username": "admin", "password": "test12345678"})
    client.post("/api/auth/logout")

    r = client.post("/api/auth/login",
                    json={"username": "admin", "password": "test12345678"})
    assert r.status_code == 200
    assert "pdb_session" in r.cookies

    r = client.get("/api/auth/status")
    assert r.json()["is_authenticated"] is True
    assert r.json()["user"]["role"] == "admin"


def test_logout_invalidates_session(client):
    client.post("/api/setup/admin",
                json={"username": "admin", "password": "test12345678"})
    assert client.get("/api/auth/status").json()["is_authenticated"] is True
    client.post("/api/auth/logout")
    assert client.get("/api/auth/status").json()["is_authenticated"] is False


def test_change_password(client):
    client.post("/api/setup/admin",
                json={"username": "admin", "password": "test12345678"})
    r = client.post("/api/auth/change_password",
                    json={"old_password": "test12345678",
                          "new_password": "newpass87654321"})
    assert r.status_code == 200

    client.post("/api/auth/logout")
    r = client.post("/api/auth/login",
                    json={"username": "admin", "password": "test12345678"})
    assert r.status_code == 401
    r = client.post("/api/auth/login",
                    json={"username": "admin", "password": "newpass87654321"})
    assert r.status_code == 200


def test_sha256_hash_rejected(monkeypatch, tmp_path, clean_auth_db):
    """[STAGE2] Старый SHA256-хэш НЕ должен приниматься (fallback удалён)."""
    import importlib
    import hashlib
    from datetime import datetime

    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sha2.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)

    from app import SessionLocal
    from models import User

    db = SessionLocal()
    try:
        u = User(
            username="legacy",
            password_hash=hashlib.sha256(b"pass1234").hexdigest(),
            role="admin", is_active=1,
            created_at=datetime.utcnow(),
        )
        db.add(u)
        db.commit()
    finally:
        db.close()

    client = TestClient(app_mod.app)
    r = client.post("/api/auth/login",
                    json={"username": "legacy", "password": "pass1234"})
    assert r.status_code == 401, (
        f"legacy SHA256 должен быть отклонён, получено "
        f"{r.status_code}: {r.text[:200]}"
    )


def test_argon2_hash_accepted(monkeypatch, tmp_path, clean_auth_db):
    """[STAGE2] Контроль: argon2-хэш работает (не сломали хороший путь)."""
    import importlib
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "argon2.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)

    client = TestClient(app_mod.app)
    r = client.post("/api/setup/admin",
                    json={"username": "admin",
                          "password": "admin12345678"})
    assert r.status_code == 200, r.text
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login",
                    json={"username": "admin",
                          "password": "admin12345678"})
    assert r.status_code == 200, r.text
