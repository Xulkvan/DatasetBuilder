"""Stage 5.4 — startup warning for METRICS_AUTH=off in production.

Регрессия: /api/metrics публичен по умолчанию и в проде это утечка
(кто угодно видит request rate, error rate, latency). Startup warning
обязан срабатывать только в ENV=prod + METRICS_AUTH=off, чтобы
разработчики не получали шум каждый раз при DEBUG=1.
"""
import importlib
import logging

from fastapi.testclient import TestClient


def _reload_app(monkeypatch, tmp_path, env_val, metrics_val, db_name):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / db_name))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("CSRF_STRICT", "0")
    monkeypatch.setenv("ENV", env_val)
    if metrics_val is None:
        monkeypatch.delenv("METRICS_AUTH", raising=False)
    else:
        monkeypatch.setenv("METRICS_AUTH", metrics_val)
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return app_mod


def test_warns_when_metrics_off_in_prod(monkeypatch, tmp_path, caplog, clean_auth_db):
    with caplog.at_level(logging.WARNING):
        app_mod = _reload_app(monkeypatch, tmp_path, "prod", "off", "m_off.db")
        with TestClient(app_mod.app):
            pass
    msgs = [r.getMessage() for r in caplog.records]
    found = [m for m in msgs
             if "METRICS_AUTH=off" in m and "ENV=prod" in m]
    assert found, (
        "Startup warning for METRICS_AUTH=off+ENV=prod not found. "
        f"Got: {msgs}"
    )


def test_no_warn_when_metrics_basic_in_prod(monkeypatch, tmp_path, caplog, clean_auth_db):
    with caplog.at_level(logging.WARNING):
        app_mod = _reload_app(monkeypatch, tmp_path, "prod", "basic", "m_basic.db")
        with TestClient(app_mod.app):
            pass
    bad = [r.getMessage() for r in caplog.records
           if "METRICS_AUTH=off" in r.getMessage()]
    assert not bad, f"Unexpected warning: {bad}"


def test_no_warn_when_metrics_off_outside_prod(monkeypatch, tmp_path, caplog, clean_auth_db):
    with caplog.at_level(logging.WARNING):
        app_mod = _reload_app(monkeypatch, tmp_path, "dev", "off", "m_dev.db")
        with TestClient(app_mod.app):
            pass
    bad = [r.getMessage() for r in caplog.records
           if "METRICS_AUTH=off" in r.getMessage()
           and "ENV=prod" in r.getMessage()]
    assert not bad, f"Unexpected warning outside prod: {bad}"
