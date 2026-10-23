"""[STAGE1-B:reid-module] ReID embeddings via simple HSV histogram (no external deps)."""
from __future__ import annotations

import hashlib
import io
import logging
import os
import threading
from collections import OrderedDict

log = logging.getLogger("db")

_CACHE: "OrderedDict[str, list]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 2000


def _crop_hash(data) -> str:
    if isinstance(data, (bytes, bytearray)):
        return hashlib.md5(bytes(data)).hexdigest()
    try:
        with open(data, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except OSError:
        return ""


def embed_from_crop(crop_img_bytes: bytes) -> list:
    """L2-normalized 48-dim HSV-ish histogram (baseline for pilot)."""
    key = _crop_hash(crop_img_bytes)
    if key:
        with _CACHE_LOCK:
            if key in _CACHE:
                _CACHE.move_to_end(key)
                return _CACHE[key]
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(crop_img_bytes)).convert("RGB").resize((32, 32))
        px = list(img.getdata())
        bins = [0] * 48
        for r, g, b in px:
            v = (r + g + b) / 3.0
            bins[int(v / 256 * 16)] += 1
            bins[16 + int(r / 256 * 16)] += 1
            bins[32 + int(g / 256 * 16)] += 1
        s = sum(bins) or 1
        vec = [x / s for x in bins]
        n = sum(x * x for x in vec) ** 0.5 or 1.0
        vec = [x / n for x in vec]
    except Exception:
        log.exception("reid: embed failed")
        return []
    if key:
        with _CACHE_LOCK:
            _CACHE[key] = vec
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
    return vec


def cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    return sum(x * y for x, y in zip(a, b))
