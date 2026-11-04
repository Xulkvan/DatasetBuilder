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
