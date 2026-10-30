# [PATCH:STAGE4_MODEL_CACHE]
"""[STAGE4] Единый ModelCache для YOLO и SAM."""
import gc
import threading
import time
from collections import OrderedDict


class ModelCache:
    def __init__(self, max_size=2, ttl_seconds=600):
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key not in self._cache:
                return None
            val, ts = self._cache[key]
            if time.time() - ts > self.ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            self._cache[key] = (val, time.time())
            return val

    def put(self, key, value):
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            self._cache[key] = (value, time.time())
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def clear(self):
        with self._lock:
            self._cache.clear()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()

    def cleanup(self):
        now = time.time()
        expired = []
        with self._lock:
            for k, (v, ts) in list(self._cache.items()):
                if now - ts > self.ttl:
                    expired.append(k)
                    del self._cache[k]
        if expired:
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            gc.collect()
# [/PATCH:STAGE4_MODEL_CACHE]
