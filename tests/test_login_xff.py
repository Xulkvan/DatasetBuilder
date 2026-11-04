"""[PATCH:STAGE1-C5] X-Forwarded-For handling behind trusted proxy."""
import importlib

import pytest


class _FakeReq:
    def __init__(self, headers, host="10.0.0.1"):
        self.headers = headers
        self.client = type("C", (), {"host": host})()


def test_xff_trusted(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    import services.client_ip as m
    importlib.reload(m)
    req = _FakeReq({"x-forwarded-for": "1.2.3.4, 5.6.7.8"})
    assert m.get_client_ip(req) == "1.2.3.4"


def test_xff_ignored_by_default(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "0")
    import services.client_ip as m
    importlib.reload(m)
    req = _FakeReq({"x-forwarded-for": "1.2.3.4, 5.6.7.8"})
    assert m.get_client_ip(req) == "10.0.0.1"


def test_x_real_ip_fallback(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    import services.client_ip as m
    importlib.reload(m)
    req = _FakeReq({"x-real-ip": "2.3.4.5"})
    assert m.get_client_ip(req) == "2.3.4.5"


def test_no_headers_returns_client_host(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    import services.client_ip as m
    importlib.reload(m)
    req = _FakeReq({}, host="9.9.9.9")
    assert m.get_client_ip(req) == "9.9.9.9"
