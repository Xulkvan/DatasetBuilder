"""[STAGE6:test-audit] AuditLog пишется на POST/PUT/DELETE."""
import importlib
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def local_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


def test_audit_log_written(local_client):
    r = local_client.post("/api/projects",
                          data={"name": "audited", "object_class": "pig"})
    assert r.status_code == 200
    time.sleep(0.4)  # fire-and-forget
    from models import AuditLog
    from database import SessionLocal
    db = SessionLocal()
    try:
        rows = db.query(AuditLog).all()
        assert any((r.action or "").upper() == "POST" for r in rows), \
            f"no POST in audit_log; rows={[r.action for r in rows]}"
    finally:
        db.close()
