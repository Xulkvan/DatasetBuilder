"""[STAGE-2-PATCH-V3] CSP: no 'unsafe-inline' for <style> tag src (1.1)."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def local_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "csp.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


def test_csp_no_unsafe_inline_for_style_tags(local_client):
    """1.1: style-src self unsafe-inline не должно быть в CSP."""
    r = local_client.get("/")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "style-src 'self' 'unsafe-inline'" not in csp, (
        f"style-src всё ещё содержит unsafe-inline: {csp}"
    )
    assert "style-src" in csp, f"style-src отсутствует в CSP: {csp}"


def test_csp_allows_style_attr(local_client):
    """style-src-attr unsafe-inline -- допустимо (inline style=...)."""
    r = local_client.get("/")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "style-src-attr" in csp


def test_csp_core_directives(local_client):
    r = local_client.get("/")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp


def test_csp_img_data_blob_allowed(local_client):
    r = local_client.get("/")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "img-src 'self' data: blob:" in csp


def test_x_frame_options_deny(local_client):
    r = local_client.get("/")
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_nosniff_header(local_client):
    r = local_client.get("/")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_referrer_policy(local_client):
    r = local_client.get("/")
    assert r.headers.get("Referrer-Policy") == "no-referrer"
