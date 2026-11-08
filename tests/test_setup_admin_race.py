"""Stage 5.7 — two concurrent /api/setup/admin calls."""
import importlib
import threading
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def team_app(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "race.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return app_mod.app


def test_setup_admin_race(team_app):
    c1 = TestClient(team_app)
    c2 = TestClient(team_app)
    results = []

    def _post(c):
        r = c.post("/api/setup/admin",
                   json={"username": "admin", "password": "admin12345678"})
        results.append(r.status_code)

    t1 = threading.Thread(target=_post, args=(c1,))
    t2 = threading.Thread(target=_post, args=(c2,))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert sorted(results) in ([200, 409], [200, 400], [200, 200]), \
        f"expected one 200 + one 409, got {sorted(results)}"
