"""Stage 5.10 — health-check returns structured checks."""
import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def local_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "h.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


def test_health_has_checks(local_client):
    r = local_client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert "checks" in d, f"missing 'checks' field: {d}"
    checks = d["checks"]
    for key in ("db", "disk_free", "disk_write", "ffmpeg", "model"):
        assert key in checks, f"missing check: {key} in {checks}"
