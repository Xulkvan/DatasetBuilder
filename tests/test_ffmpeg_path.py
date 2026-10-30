"""[STAGE6:test-ffmpeg] Allowlist для system_ffmpeg_set_path."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def local_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ff.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


def test_arbitrary_executable_rejected(local_client, tmp_path):
    evil = tmp_path / "evil.sh"
    evil.write_text("#!/bin/sh\necho pwned\n")
    evil.chmod(0o755)
    r = local_client.post("/api/system/ffmpeg/set_path",
                          json={"path": str(evil)})
    assert r.status_code == 400


def test_empty_path_resets(local_client):
    r = local_client.post("/api/system/ffmpeg/set_path", json={"path": ""})
    assert r.status_code == 200
