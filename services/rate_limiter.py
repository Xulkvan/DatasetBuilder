import os
import time
import threading
from collections import defaultdict  # noqa: F401  (kept for backward compat)

# memory-bounded + degraded multi-worker
class RateLimitUnavailable(Exception):
    """[PATCH:STAGE1:E1-RATE-MW] raised when limiter cannot guarantee protection."""
    pass


class SimpleRateLimiter:
    def __init__(self, max_requests: int, window_sec: float,
                 max_buckets: int = 100_000,
                 fail_mode: str = "closed"):
        # fail_mode: "closed" (default) = raise 503 in degraded mode;
        #            "open" = allow all (backward compat for heavy ops).
        self.fail_mode = fail_mode if fail_mode in ("open", "closed") else "closed"
        self.max_requests = max_requests
        self.window = window_sec
        self.max_buckets = max_buckets
        self._buckets: dict = {}
        self._lock = threading.Lock()
        self._last_cleanup: float = 0.0
        _w = 0
        for _n in ("UVICORN_WORKERS", "WEB_CONCURRENCY"):
            try:
                _w = max(_w, int(os.getenv(_n, "1") or "1"))
            except (ValueError, TypeError):
                pass
        self.degraded = _w > 1
        if self.degraded:
            import logging as _lg
            _lg.getLogger("db").warning(
                "RateLimiter: multi-worker (%d) — in-memory limits disabled",
                _w)

    def check(self, key: str) -> bool:
        if self.degraded:
            # login/brute-force must fail-closed
            if self.fail_mode == "closed":
                raise RateLimitUnavailable(
                    f"Rate limiter unavailable in multi-worker: "
                    f"{self.max_requests} req / {self.window}s"
                )
            return True
        now = time.monotonic()
        with self._lock:
            # enforce capacity (с запасом +1 на текущий ключ)
            if len(self._buckets) >= self.max_buckets:
                _overflow = len(self._buckets) - self.max_buckets + 1
                _by_age = sorted(self._buckets.items(),
                                 key=lambda kv: kv[1][-1] if kv[1] else 0)
                for _k, _ in _by_age[:_overflow]:
                    self._buckets.pop(_k, None)
            # периодическая очистка истёкших
            if now - self._last_cleanup > self.window:
                self._last_cleanup = now
                _cutoff = now - self.window
                for _k in [k for k, b in self._buckets.items()
                           if not b or b[-1] <= _cutoff]:
                    self._buckets.pop(_k, None)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = []
                self._buckets[key] = bucket
            cutoff = now - self.window
            bucket[:] = [t for t in bucket if t > cutoff]
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True

_limiter_autolabel = SimpleRateLimiter(max_requests=60, window_sec=60, fail_mode="open")
_limiter_train = SimpleRateLimiter(max_requests=5, window_sec=300, fail_mode="open")
_limiter_upload = SimpleRateLimiter(max_requests=300, window_sec=60, fail_mode="open")
_limiter_import = SimpleRateLimiter(max_requests=5, window_sec=600, fail_mode="open")

def _rate_limit(limiter, key: str, msg: str | dict):
    from fastapi import HTTPException
    # fail-closed with 503 if limiter unavailable
    try:
        allowed = limiter.check(key)
    except RateLimitUnavailable as _rl_exc:
        raise HTTPException(503, {
            "key": "error.rateLimiterUnavailable",
            "fallback": "Rate limiter unavailable (multi-worker). "
                        "Configure WEB_CONCURRENCY=1 or use a shared limiter.",
            "params": {"reason": str(_rl_exc)},
        })
    if not allowed:
        raise HTTPException(429, msg)
