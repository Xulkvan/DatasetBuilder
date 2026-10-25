"""[STAGE1:reid-v2] ReID embeddings.

Приоритет:
  1. torchreid (если установлен)
  2. torchvision.models.resnet18 (предобученный, L2-normalized)
  3. HSV-гистограмма (fallback без зависимостей)
"""
from __future__ import annotations

import hashlib
import io
import logging
import threading
from collections import OrderedDict

log = logging.getLogger("db")

_CACHE: "OrderedDict[str, list]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 2000

_TORCH_READY = False
_TORCH_KIND = "none"     # torchreid | torchvision | none
_DEVICE = "cpu"
_TRANSFORM = None
_MODEL = None


def _hash_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _init_torch():
    global _TORCH_READY, _TORCH_KIND, _DEVICE, _TRANSFORM, _MODEL
    if _TORCH_READY:
        return
    _TORCH_READY = True
    try:
        import torch
        _DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        _TORCH_KIND = "none"
        return
    # 1) torchreid
    try:
        import torchreid
        _MODEL = torchreid.models.build_model(
            name="osnet_x0_25", num_classes=1000, pretrained=True)
        _MODEL = _MODEL.to(_DEVICE).eval()
        _TORCH_KIND = "torchreid"
        log.info("ReID: torchreid OSNet-x0.25 on %s", _DEVICE)
        return
    except Exception:
        pass
    # 2) torchvision resnet18
    try:
        from torchvision import models, transforms
        weights = models.ResNet18_Weights.DEFAULT
        m = models.resnet18(weights=weights)
        m.fc = m.fc.__class__(m.fc.in_features, 512, bias=True)
        _MODEL = m.to(_DEVICE).eval()
        _TRANSFORM = transforms.Compose([
            transforms.Resize((128, 64)),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]),
        ])
        _TORCH_KIND = "torchvision"
        log.info("ReID: torchvision resnet18 on %s", _DEVICE)
    except Exception as e:
        log.info("ReID: torch unavailable, fallback HSV (%s)", e)
        _TORCH_KIND = "none"


def _embed_torch(img):
    import torch
    t = _TRANSFORM(img).unsqueeze(0).to(_DEVICE)
    with torch.no_grad():
        feat = _MODEL(t).flatten(1)
        feat = feat / feat.norm(dim=1, keepdim=True).clamp_min(1e-8)
    return feat.squeeze(0).cpu().tolist()


def _embed_hsv(img) -> list:
    px = list(img.convert("RGB").resize((32, 32)).getdata())
    bins = [0] * 48
    for r, g, b in px:
        v = (r + g + b) / 3.0
        bins[int(v / 256 * 16)] += 1
        bins[16 + int(r / 256 * 16)] += 1
        bins[32 + int(g / 256 * 16)] += 1
    s = sum(bins) or 1
    vec = [x / s for x in bins]
    n = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / n for x in vec]


def embed_from_crop(crop_img_bytes: bytes) -> list:
    """L2-normalized embedding вектор (torchreid / resnet18 / HSV)."""
    key = _hash_bytes(crop_img_bytes)
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]

    _init_torch()
    vec: list = []
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(crop_img_bytes)).convert("RGB")
        if _TORCH_KIND in ("torchreid", "torchvision"):
            vec = _embed_torch(img)
        else:
            vec = _embed_hsv(img)
    except Exception:
        log.exception("reid: embed failed")
        return []

    if key and vec:
        with _CACHE_LOCK:
            _CACHE[key] = vec
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
    return vec


def cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    return float(sum(x * y for x, y in zip(a, b)))
