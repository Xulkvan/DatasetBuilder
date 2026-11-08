"""Stage 5.7 — /api/docs contract sanity."""
import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def local_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "o.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


def test_openapi_available(local_client):
    r = local_client.get("/openapi.json")
    assert r.status_code == 200, r.text
    d = r.json()
    assert "paths" in d
    assert len(d["paths"]) > 0


def test_api_docs(local_client):
    r = local_client.get("/api/docs")
    assert r.status_code == 200
