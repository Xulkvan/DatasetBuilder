"""[PATCH:STAGE1-F-05] RateLimiter memory bound + degraded mode."""
import importlib
import os

from services.rate_limiter import SimpleRateLimiter


def test_memory_bounded():
    """При 100k max_buckets — 500 уникальных ключей вмещаются без проблем."""
    rl = SimpleRateLimiter(max_requests=5, window_sec=60, max_buckets=100)
    for i in range(500):
        rl.check(f"k{i}")
    assert len(rl._buckets) <= 100 + 1, f"unbounded: {len(rl._buckets)}"


def test_memory_bound_with_purge():
    """При переполнении старые bucket'ы вытесняются."""
    rl = SimpleRateLimiter(max_requests=5, window_sec=60, max_buckets=50)
    for i in range(300):
        rl.check(f"key_{i}")
    assert len(rl._buckets) <= 51


# Stage 1 (1.8) changed default fail_mode to "closed".
# Old test expected fail-open; split into two to cover both modes explicitly.
def test_degraded_multiworker_fail_closed(monkeypatch):
    """[PATCH:STAGE1:E1-RATE-MW] default fail_mode='closed' raises RateLimitUnavailable."""
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    importlib.reload(__import__("services.rate_limiter", fromlist=["x"]))
    from services import rate_limiter as rl_mod
    rl = rl_mod.SimpleRateLimiter(max_requests=1, window_sec=60)
    assert rl.degraded is True
    assert rl.fail_mode == "closed"
    import pytest as _pytest_rc
    with _pytest_rc.raises(rl_mod.RateLimitUnavailable):
        rl.check("same_key")


def test_degraded_multiworker_fail_open(monkeypatch):
    """[PATCH:STAGE1:E1-RATE-MW] fail_mode='open' allows all in degraded mode."""
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    importlib.reload(__import__("services.rate_limiter", fromlist=["x"]))
    from services import rate_limiter as rl_mod
    rl = rl_mod.SimpleRateLimiter(max_requests=1, window_sec=60,
                                   fail_mode="open")
    assert rl.degraded is True
    assert rl.fail_mode == "open"
    for _ in range(10):
        assert rl.check("same_key") is True

def test_default_not_degraded(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)
    importlib.reload(__import__("services.rate_limiter", fromlist=["x"]))
    from services import rate_limiter as rl_mod
    rl = rl_mod.SimpleRateLimiter(max_requests=1, window_sec=60)
    assert rl.degraded is False
    assert rl.check("k") is True
    assert rl.check("k") is False  # second over limit


def test_username_bomb_bounded():
    """Brute-force уникальными username не растит _buckets бесконечно."""
    rl = SimpleRateLimiter(max_requests=5, window_sec=300, max_buckets=200)
    for i in range(5000):
        rl.check(f"user_{i}")
    assert len(rl._buckets) <= 201
