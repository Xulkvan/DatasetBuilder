"""SAM model loading and inference."""
import io
import base64
import logging
import os
import threading
from typing import Optional

from PIL import Image
from database import SessionLocal
from models import Setting
from config import DEFAULT_SAM_MODEL, VALID_SAM_MODELS, SETTING_SAM_MODEL

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

log = logging.getLogger("db")

# [PATCH:STAGE4_SAM_SHARED_CACHE]
from services.model_cache import ModelCache  # noqa: F401

_SAM_CACHE = ModelCache(max_size=1, ttl_seconds=600)
# [/PATCH:STAGE4_SAM_SHARED_CACHE]
_SAM_LAST_IMAGE_KEY = None

def get_sam_model_name(db) -> str:
    row = db.query(Setting).filter(Setting.key == SETTING_SAM_MODEL).first()
    name = row.value if row else DEFAULT_SAM_MODEL
    if name not in VALID_SAM_MODELS: name = DEFAULT_SAM_MODEL
    return name

def _get_sam_model(model_name: str):
    m = _SAM_CACHE.get(model_name)
    if m is not None: return m
    from ultralytics import SAM
    m = SAM(model_name)
    _SAM_CACHE.put(model_name, m)
    return m

def _clear_sam_cache():
    global _SAM_LAST_IMAGE_KEY
    _SAM_CACHE.clear()
    _SAM_LAST_IMAGE_KEY = None

def _bbox_from_mask_np(mask_np):
    if not _HAS_NUMPY: return None
    try:
        rows = _np.any(mask_np, axis=1)
        cols = _np.any(mask_np, axis=0)
        if not rows.any() or not cols.any(): return None
        ys = _np.where(rows)[0]
        xs = _np.where(cols)[0]
        return float(xs[0]), float(ys[0]), float(xs[-1] + 1), float(ys[-1] + 1)
    except Exception: return None

def _extract_sam_result(r):
    mask_np = None
    try:
        if getattr(r, "masks", None) is not None and len(r.masks.data) > 0:
            mask_np = r.masks.data[0].cpu().numpy()
    except Exception: pass

    bbox_px = None
    if mask_np is not None: bbox_px = _bbox_from_mask_np(mask_np)

    if bbox_px is None and getattr(r, "boxes", None) is not None and len(r.boxes) > 0:
        try:
            xyxy = r.boxes.xyxy.cpu().numpy()
            if len(xyxy) > 0:
                x1, y1, x2, y2 = xyxy[0].tolist()
                bbox_px = (float(x1), float(y1), float(x2), float(y2))
        except Exception: pass

    if bbox_px is None: return None

    score = 1.0
    try:
        if getattr(r, "boxes", None) is not None and getattr(r.boxes, "conf", None) is not None:
            cf = r.boxes.conf.cpu().numpy()
            if len(cf) > 0: score = float(cf[0])
    except Exception: pass

    mask_b64 = ""
    if mask_np is not None:
        try:
            small = Image.fromarray((mask_np > 0.5).astype("uint8") * 255)
            small = small.resize((160, 160), Image.Resampling.NEAREST)
            buf = io.BytesIO()
            small.save(buf, format="PNG", optimize=True)
            mask_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception: pass
    return {"bbox_px": bbox_px, "score": score, "mask_b64": mask_b64}

def _run_sam_predict(model, img_path: str, points_px: list, labels: list):
    global _SAM_LAST_IMAGE_KEY
    if _SAM_LAST_IMAGE_KEY == img_path:
        predictor = getattr(model, "predictor", None)
        if predictor is not None:
            try:
                results = predictor(points=points_px, labels=labels)
                if results:
                    res = _extract_sam_result(results[0])
                    if res: return res
            except Exception:
                _SAM_LAST_IMAGE_KEY = None

    results = model(img_path, points=points_px, labels=labels, verbose=False)
    if not results: return None
    _SAM_LAST_IMAGE_KEY = img_path
    return _extract_sam_result(results[0])
