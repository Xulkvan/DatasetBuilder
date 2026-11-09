"""[STAGE9_DNS_PINNING] Tests for services/safe_http_client.

Регрессия: до STAGE9 внешние fetch (import_url, webhooks, внешние
коннекторы) использовали urllib.request напрямую — double-resolve
в is_safe_external_url защищал от наивного DNS rebinding, но не
от «умного»: attacker держит публичный IP 50 мс, urllib резолвит
заново → connect идёт на приватный IP (TOCTOU).

После STAGE9 _PinnedTransport:
  * резолвит host один раз;
  * проверяет каждый IP через _is_private_ip;
  * коннектится к pin_ip, Host передаётся заголовком.
"""
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from services import url_safety


def _start_mock_server():
    """Запускает HTTP-сервер на 127.0.0.1:0 и возвращает (srv, port)."""
    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_GET(self):
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass

    try:
        srv = HTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as _e:
        pytest.skip(f"Cannot start mock HTTP server: {_e}")

    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, port


class TestPinnedTransport:
    def test_private_loopback_blocked(self):
        """http://127.0.0.1/ — блокируется ДО реального connect."""
        from services.safe_http_client import get_safe_client

        with get_safe_client(timeout=2.0) as c:
            with pytest.raises(httpx.ConnectError) as ei:
                c.get("http://127.0.0.1:1/")

        msg = str(ei.value).lower()
        assert "private" in msg or "blocked" in msg, (
            f"unexpected error: {ei.value}"
        )

    def test_private_ip_via_dns_blocked(self, monkeypatch):
        """Fake DNS → приватный IP → ConnectError без реального connect."""
        from services.safe_http_client import get_safe_client

        def _fake_getaddrinfo(host, port, *a, **kw):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     ("192.168.1.1", port or 80))]

        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)

        with get_safe_client(timeout=2.0) as c:
            with pytest.raises(httpx.ConnectError) as ei:
                c.get("http://example.com/")

        msg = str(ei.value).lower()
        assert "private" in msg or "blocked" in msg, (
            f"unexpected error: {ei.value}"
        )

    def test_public_ip_success_with_mock_server(self, monkeypatch):
        """Fake DNS → 127.0.0.1 (loopback разрешён через _is_private_ip
        monkeypatch) → connect идёт на 127.0.0.1:PORT, Host-заголовок
        сохраняет оригинальный hostname.
        """
        from services.safe_http_client import get_safe_client

        srv, port = _start_mock_server()
        try:
            def _fake_getaddrinfo(host, port_arg, *a, **kw):
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                         ("127.0.0.1", port_arg or 80))]

            monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
            monkeypatch.setattr(url_safety, "_is_private_ip", lambda ip: False)

            with get_safe_client(timeout=5.0) as c:
                r = c.get(f"http://example.com:{port}/")
            assert r.status_code == 200
            assert r.text == "ok"
        finally:
            srv.shutdown()
            srv.server_close()

    def test_https_fallback_blocks_private(self):
        """https:// для приватного URL падает через is_safe_external_url
        (без реального HTTPS-соединения)."""
        from services.safe_http_client import get_safe_client

        with get_safe_client(timeout=2.0) as c:
            with pytest.raises(httpx.ConnectError) as ei:
                c.get("https://127.0.0.1/")

        msg = str(ei.value).lower()
        assert "unsafe" in msg or "blocked" in msg, (
            f"unexpected error: {ei.value}"
        )

    def test_redirect_to_private_ip_blocked(self, monkeypatch):
        """Редирект на приватный IP блокируется на втором хопе.

        httpx.Client следует редиректам, вызывая транспорт заново.
        PinnedTransport перехватывает второй запрос и блокирует его.
        """
        from services.safe_http_client import get_safe_client

        class _RedirectHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()

            def log_message(self, *args): pass

        try:
            srv = HTTPServer(("127.0.0.1", 0), _RedirectHandler)
        except OSError as _e:
            pytest.skip(f"Cannot start mock HTTP server: {_e}")

        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        orig_getaddrinfo = socket.getaddrinfo
        def _fake_getaddrinfo(host, p, *a, **kw):
            if host == "example.com":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", p or 80))]
            return orig_getaddrinfo(host, p, *a, **kw)

        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)

        # Разрешаем 127.0.0.1 только для первого хопа (иначе _PinnedTransport
        # заблокирует наш mock-сервер). На втором хопе будет 169.254.169.254 —
        # он должен быть заблокирован оригинальным _is_private_ip.
        orig_is_private = url_safety._is_private_ip
        def _fake_is_private(ip):
            if str(ip) == "127.0.0.1":
                return False
            return orig_is_private(ip)

        monkeypatch.setattr(url_safety, "_is_private_ip", _fake_is_private)

        try:
            with get_safe_client(timeout=2.0) as c:
                with pytest.raises(httpx.ConnectError) as ei:
                    c.get(f"http://example.com:{port}/")
            msg = str(ei.value).lower()
            assert "private" in msg or "blocked" in msg, f"unexpected error: {ei.value}"
        finally:
            srv.shutdown()
            srv.server_close()


class TestGetSafeClientShape:
    def test_returns_httpx_client(self):
        from services.safe_http_client import get_safe_client
        with get_safe_client() as c:
            assert isinstance(c, httpx.Client)

    def test_follow_redirects_on(self):
        from services.safe_http_client import get_safe_client
        with get_safe_client() as c:
            assert c.follow_redirects is True

    def test_default_timeout(self):
        from services.safe_http_client import get_safe_client
        with get_safe_client(timeout=7.5) as c:
            assert c.timeout is not None


class TestWebhookAllowPrivate:
    def test_webhook_allow_private_bypasses_pinning(self, monkeypatch):
        """При WEBHOOK_ALLOW_PRIVATE=1 _post_once использует обычный httpx.Client,
        а не get_safe_client (pinning отключён)."""
        from services import webhook_service
        calls = []

        class MockClient:
            def __init__(self, *a, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def post(self, url, content, headers):
                calls.append(url)
                return httpx.Response(200)

        monkeypatch.setattr(httpx, "Client", MockClient)
        monkeypatch.setattr(webhook_service, "_allow_private_webhooks", lambda: True)

        res = webhook_service._post_once("http://127.0.0.1/hook", b"{}", "sig")

        assert res is True
        assert calls == ["http://127.0.0.1/hook"]
