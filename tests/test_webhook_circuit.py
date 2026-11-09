"""Stage 5.5 — webhook circuit breaker.

Регрессия: при недоступном получателе webhook'и каждый раз бьют 3 попытки
с backoff (1+2+4s), это шторм в логах и задержка fire-and-forget. Circuit
breaker: 5 подряд неудач → 15-минутный блок, успех — сбрасывает.
"""
import time

import pytest

import services.webhook_service as ws


@pytest.fixture(autouse=True)
def _clean_circuit():
    with ws._CIRCUIT_LOCK:
        ws._FAILED_WEBHOOKS.clear()
    yield
    with ws._CIRCUIT_LOCK:
        ws._FAILED_WEBHOOKS.clear()


def test_circuit_opens_after_threshold_failures(monkeypatch):
    monkeypatch.setattr(ws, "_post_once", lambda u, p, s: False)
    monkeypatch.setattr(ws, "BACKOFF", [0.0, 0.0, 0.0])
    url = "https://example.com/hook"
    for _ in range(ws._CIRCUIT_FAIL_THRESHOLD):
        assert ws._send_with_retry(url, b"{}", "") is False
    assert ws._circuit_is_open(url) is True


def test_open_circuit_skips_http(monkeypatch):
    monkeypatch.setattr(ws, "_post_once", lambda u, p, s: False)
    monkeypatch.setattr(ws, "BACKOFF", [0.0, 0.0, 0.0])
    url = "https://example.com/hook2"
    for _ in range(ws._CIRCUIT_FAIL_THRESHOLD):
        ws._send_with_retry(url, b"{}", "")

    calls = []

    def _fake_post(u, p, s):
        calls.append(u)
        return False

    monkeypatch.setattr(ws, "_post_once", _fake_post)
    assert ws._send_with_retry(url, b"{}", "") is False
    assert calls == [], "circuit open must skip _post_once"


def test_success_resets_circuit(monkeypatch):
    monkeypatch.setattr(ws, "_post_once", lambda u, p, s: True)
    url = "https://example.com/hook3"
    with ws._CIRCUIT_LOCK:
        ws._FAILED_WEBHOOKS[url] = {"fails": 3, "blocked_until": 0.0}
    assert ws._send_with_retry(url, b"{}", "") is True
    with ws._CIRCUIT_LOCK:
        assert url not in ws._FAILED_WEBHOOKS


def test_blocked_until_expires(monkeypatch):
    url = "https://example.com/hook4"
    with ws._CIRCUIT_LOCK:
        ws._FAILED_WEBHOOKS[url] = {
            "fails": 10, "blocked_until": time.time() - 1,
        }
    assert ws._circuit_is_open(url) is False
    with ws._CIRCUIT_LOCK:
        assert url not in ws._FAILED_WEBHOOKS
