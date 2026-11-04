import os
import time
import threading
from collections import defaultdict  # noqa: F401  (kept for backward compat)

# [PATCH:STAGE1-F-05-C4] memory-bounded + degraded multi-worker
class SimpleRateLimiter:
    def __init__(self, max_requests: int, window_sec: float,
                 max_buckets: int = 100_000):
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
            # fail-open: in-memory limiter не работает между воркерами
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

_limiter_autolabel = SimpleRateLimiter(max_requests=60, window_sec=60)
_limiter_train = SimpleRateLimiter(max_requests=5, window_sec=300)
_limiter_upload = SimpleRateLimiter(max_requests=300, window_sec=60)
_limiter_import = SimpleRateLimiter(max_requests=5, window_sec=600)

def _rate_limit(limiter, key: str, msg: str | dict):
    from fastapi import HTTPException
    if not limiter.check(key):
        raise HTTPException(429, msg)
