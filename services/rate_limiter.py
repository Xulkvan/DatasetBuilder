import time
import threading
from collections import defaultdict

class SimpleRateLimiter:
    def __init__(self, max_requests: int, window_sec: float):
        self.max_requests = max_requests
        self.window = window_sec
        self._buckets = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets[key]
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

def _rate_limit(limiter, key: str, msg: str):
    from fastapi import HTTPException
    if not limiter.check(key):
        raise HTTPException(429, msg)
