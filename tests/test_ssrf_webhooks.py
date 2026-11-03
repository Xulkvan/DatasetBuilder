"""[STAGE5] Webhook SSRF: запросы на приватные IP блокируются.

Проверяет:
  * _post_once возвращает False и НЕ отправляет запрос на localhost;
  * _safe_webhook_url блокирует private ranges;
  * WEBHOOK_ALLOW_PRIVATE=1 отключает блокировку (для локальной разработки);
  * API: webhook можно создать с localhost-URL, но /test вернёт ok=False.
"""
import os
import socket
import threading

import pytest

from services.url_safety import is_safe_external_url


def _start_socket_counter(host="127.0.0.1", timeout=0.6):
    """TCP-сокет, считающий входящие соединения. Возвращает (port, received, thread, close_fn)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    sock.listen(1)
    sock.settimeout(timeout)
    port = sock.getsockname()[1]
    received = []

    def acceptor():
        try:
            conn, _ = sock.accept()
            received.append(1)
            conn.close()
        except (socket.timeout, OSError):
            pass

    t = threading.Thread(target=acceptor, daemon=True)
    t.start()

    def close():
        try:
            sock.close()
        except OSError:
            pass
    return port, received, t, close


def test_localhost_webhook_blocked():
    """_post_once на 127.0.0.1 возвращает False и НЕ шлёт запрос."""
    from services.webhook_service import _post_once
    os.environ.pop("WEBHOOK_ALLOW_PRIVATE", None)

    port, received, t, close = _start_socket_counter()
    try:
        ok = _post_once(f"http://127.0.0.1:{port}/hook", b"{}", "")
        assert ok is False, "SSRF guard должен вернуть False"
        t.join(timeout=1.5)
        assert not received, "SSRF guard пропустил запрос: socket получил соединение"
    finally:
        close()


def test_metadata_ip_blocked():
    from services.webhook_service import _post_once
    os.environ.pop("WEBHOOK_ALLOW_PRIVATE", None)
    ok = _post_once("http://169.254.169.254/latest/meta-data/", b"{}", "")
    assert ok is False


def test_private_ips_blocked():
    from services.webhook_service import _safe_webhook_url
    assert _safe_webhook_url("http://192.168.1.1/hook") is False
    assert _safe_webhook_url("http://10.0.0.1/hook") is False
    assert _safe_webhook_url("http://172.16.0.1/hook") is False


def test_safe_url_passes_guard(monkeypatch):
    """Публичные URL (симулируем getaddrinfo) — проходят фильтр."""
    def fake_getaddrinfo(host, port):
        return [(2, 1, 6, "", ("1.1.1.1", 0))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    from services.webhook_service import _safe_webhook_url
    assert _safe_webhook_url("https://example.com/hook") is True
    assert is_safe_external_url("https://example.com/hook") is True


def test_allow_private_opt_in(monkeypatch):
    """WEBHOOK_ALLOW_PRIVATE=1 — блокировка отключается (для тестов)."""
    from services.webhook_service import _allow_private_webhooks
    monkeypatch.setenv("WEBHOOK_ALLOW_PRIVATE", "1")
    assert _allow_private_webhooks() is True
    monkeypatch.setenv("WEBHOOK_ALLOW_PRIVATE", "0")
    assert _allow_private_webhooks() is False


def test_non_http_schemes_blocked():
    assert is_safe_external_url("file:///etc/passwd") is False
    assert is_safe_external_url("ftp://example.com/") is False
    assert is_safe_external_url("javascript:alert(1)") is False


def test_webhook_api_localhost_creation_allowed_but_test_blocked(
        monkeypatch, tmp_path, clean_auth_db):
    """API-level: создание webhook с localhost → 200, /test → ok=False."""
    import importlib
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ssrf_api.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    os.environ.pop("WEBHOOK_ALLOW_PRIVATE", None)
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    client = TestClient(
        app_mod.app, headers={"X-Requested-With": "DatasetBuilder"})

    r = client.post("/api/projects", data={"name": "ssrf_api", "object_class": "pig"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    r = client.post(
        f"/api/projects/{pid}/webhooks",
        json={"url": "http://127.0.0.1:65534/hook",
              "event_type": "annotation.saved",
              "secret_key": ""},
    )
    assert r.status_code == 200, r.text
    wh_id = r.json()["id"]

    r = client.post(f"/api/webhooks/{wh_id}/test")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False, (
        "SSRF guard должен блокировать localhost в /test")
