"""[STAGE0-4] CSRF double-submit: при CSRF_STRICT=1 запрос без токена → 403.

В local-mode auth_status cookie pdb_csrf не выставляет, поэтому тесты
передают cookie через httpx-параметр cookies={...} на каждый запрос.
Так double-submit-логика security.py проверяется без зависимости от
режима аутентификации.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

_CSRF_TOKEN = "test_token_123"


@pytest.fixture
def strict_client(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "csrf.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("CSRF_STRICT", "1")

    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)

    return TestClient(app_mod.app)


def test_post_without_csrf_header_rejected(strict_client):
    """Cookie pdb_csrf есть, X-CSRF-Token отсутствует → 403."""
    r = strict_client.post(
        "/api/projects",
        data={"name": "x", "object_class": "pig"},
        headers={"X-Requested-With": "DatasetBuilder"},
        cookies={"pdb_csrf": _CSRF_TOKEN},
    )
    assert r.status_code == 403, r.text
    assert "CSRF" in r.text, f"ожидали упоминание CSRF, получили: {r.text[:200]}"


def test_post_with_matching_csrf_token_accepted(strict_client):
    """Cookie и X-CSRF-Token совпадают → запрос проходит."""
    r = strict_client.post(
        "/api/projects",
        data={"name": "x", "object_class": "pig"},
        headers={
            "X-Requested-With": "DatasetBuilder",
            "X-CSRF-Token": _CSRF_TOKEN,
        },
        cookies={"pdb_csrf": _CSRF_TOKEN},
    )
    assert r.status_code == 200, r.text


def test_post_with_wrong_csrf_token_rejected(strict_client):
    """Cookie есть, X-CSRF-Token не совпадает → 403."""
    r = strict_client.post(
        "/api/projects",
        data={"name": "x", "object_class": "pig"},
        headers={
            "X-Requested-With": "DatasetBuilder",
            "X-CSRF-Token": "definitely-wrong",
        },
        cookies={"pdb_csrf": _CSRF_TOKEN},
    )
    assert r.status_code == 403, r.text
    assert "CSRF" in r.text

# [PATCH:STAGE1-F-04]
def test_local_mode_sets_csrf_cookie(monkeypatch, tmp_path, clean_auth_db):
    """[STAGE1-F-04] GET / в local mode -> Set-Cookie: pdb_csrf=..."""
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "local_csrf.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("CSRF_STRICT", "0")
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    c = TestClient(app_mod.app)
    r = c.get("/")
    assert r.status_code == 200
    assert "pdb_csrf" in r.cookies, (
        f"pdb_csrf cookie not set in local mode; cookies={dict(r.cookies)}")


def test_local_mode_post_after_get(monkeypatch, tmp_path, clean_auth_db):
    """[STAGE1-F-04] После GET / POST с cookie+header принимается."""
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "local_csrf2.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("CSRF_STRICT", "1")
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    c = TestClient(app_mod.app)
    r = c.get("/")
    token = r.cookies.get("pdb_csrf")
    assert token
    r = c.post("/api/projects",
               data={"name": "x", "object_class": "pig"},
               headers={"X-Requested-With": "DatasetBuilder",
                        "X-CSRF-Token": token})
    assert r.status_code == 200, r.text


def test_post_without_csrf_cookie_strict_mode(monkeypatch, tmp_path, clean_auth_db):
    """[STAGE1-C12] STRICT=1: cookie отсутствует -> 403."""
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "local_csrf3.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("CSRF_STRICT", "1")
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    c = TestClient(app_mod.app)
    # NB: NO GET / — cookie отсутствует
    r = c.post("/api/projects",
               data={"name": "x", "object_class": "pig"},
               headers={"X-Requested-With": "DatasetBuilder"})
    assert r.status_code == 403, r.text
    assert "CSRF" in r.text

