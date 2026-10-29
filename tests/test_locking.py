# [PATCH:STAGE8-test-locking]
"""Soft locks: TTL, busy, heartbeat."""
from config import LOCK_TTL_SECONDS


def test_lock_ttl_config():
    assert 60 <= LOCK_TTL_SECONDS <= 3600


def test_lock_endpoint_exists(monkeypatch, tmp_path):
    import importlib
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import app as app_mod
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    client = TestClient(app_mod.app)
    client.post("/api/setup/admin",
                json={"username": "admin", "password": "admin12345678"})
    r = client.post("/api/images/999999/lock")
    assert r.status_code != 405
