"""[STAGE3:DEDUP-EXPORT] Helpers for YOLO/COCO export.

Вынесены из app.py в Stage 3 (3.1), чтобы:
  * убрать дублирующуюся логику из app.py,
  * дать routers/projects.py доступ к тем же helpers без циклических импортов,
  * упростить юнит-тестирование.

Публичные функции:
  * _build_letterbox_meta(images, fixed_size=FIXED_SIZE) -> dict
  * _split_images(images, split_spec) -> {'train','val','test'}
  * _kp_yolo_row(ann, kps_by_ann, schema, force_pad) -> str
  * _project_has_keypoints(db, project_id) -> bool
"""
from __future__ import annotations

import random

from sqlalchemy import func
from sqlalchemy.orm import Session

from config import FIXED_SIZE, KEYPOINT_SCHEMA
from models import Annotation, ImageModel, Keypoint


# ---------------------------------------------------------------------------
# Letterbox metadata
# ---------------------------------------------------------------------------
def _build_letterbox_meta(images, fixed_size=FIXED_SIZE) -> dict:
    """Letterbox-метаданные для каждого изображения.

    {image_id_str: {filename, original_*, new_*, pad_*, scale, transform_known}}
    """
    fw, fh = fixed_size
    out = {}
    for im in images:
        ow = getattr(im, "original_width", None)
        oh = getattr(im, "original_height", None)
        if not ow or not oh:
            ow = getattr(im, "width", None) or fw
            oh = getattr(im, "height", None) or fh
        try:
            ow = int(ow); oh = int(oh)
        except (TypeError, ValueError):
            ow, oh = fw, fh
        if ow <= 0 or oh <= 0:
            ow, oh = fw, fh
        scale = min(fw / ow, fh / oh)
        nw = ow * scale
        nh = oh * scale
        pad_x = (fw - nw) / 2.0
        pad_y = (fh - nh) / 2.0
        out[str(im.id)] = {
            "filename": im.filename,
            "original_width":  ow,
            "original_height": oh,
            "new_width":  int(fw),
            "new_height": int(fh),
            "pad_x": round(pad_x, 2),
            "pad_y": round(pad_y, 2),
            "scale": round(scale, 6),
            "transform_known": bool(getattr(im, "original_width", None)),
        }
    return out


# ---------------------------------------------------------------------------
# Train/val/test split
# ---------------------------------------------------------------------------
def _split_images(images, split_spec):
    """Разбивает images на {'train','val','test'} по split_spec ('70,20,10')."""
    if not split_spec or split_spec == "none":
        return {"train": list(images), "val": [], "test": []}
    try:
        parts = [float(x) for x in split_spec.split(",")]
        if len(parts) == 2:
            parts.append(0.0)
        if len(parts) != 3:
            raise ValueError
        total = sum(parts)
        if total <= 0:
            raise ValueError
        parts = [p / total for p in parts]
    except (ValueError, AttributeError):
        return {"train": list(images), "val": [], "test": []}

    items = list(images)
    random.Random(42).shuffle(items)
    n = len(items)
    n_val = int(round(n * parts[1]))
    n_test = int(round(n * parts[2]))
    n_train = n - n_val - n_test
    if n_train < 0:
        deficit = -n_train
        if n_test >= deficit:
            n_test -= deficit
        else:
            deficit -= n_test
            n_test = 0
            n_val = max(0, n_val - deficit)
        n_train = 0
    end_train = n_train
    end_val = end_train + n_val
    end_test = end_val + n_test
    return {
        "train": items[:end_train],
        "val": items[end_train:end_val],
        "test": items[end_val:end_test],
    }


# ---------------------------------------------------------------------------
# Keypoint helpers
# ---------------------------------------------------------------------------
def _kp_name_to_index(schema=None) -> dict:
    """{name: index} по переданной (или дефолтной) схеме."""
    if schema is None:
        schema = KEYPOINT_SCHEMA
    return {k[0]: i for i, k in enumerate(schema)}


def _kp_yolo_row(ann, kps_by_ann: dict, schema=None,
                 force_pad: bool = False) -> str:
    """YOLO-pose строка для одной аннотации.

    force_pad=True — писать пустые точки нулями даже если их нет,
    чтобы строка соответствовала kpt_shape в data.yaml.
    """
    kps = kps_by_ann.get(ann.id) or []
    base = f"0 {ann.x:.6f} {ann.y:.6f} {ann.w:.6f} {ann.h:.6f}"
    if not kps and not force_pad:
        return base
    if schema is None:
        schema = KEYPOINT_SCHEMA
    name2idx = _kp_name_to_index(schema)
    n = len(schema)
    arr = [None] * n
    for kp in kps:
        idx = name2idx.get(kp.name)
        if idx is None:
            continue
        v = 1 if float(kp.visibility or 0) >= 0.5 else 0
        arr[idx] = (float(kp.x), float(kp.y), v)
    parts = [base]
    for item in arr:
        if item is None:
            parts.append("0.000000 0.000000 0")
        else:
            x, y, v = item
            parts.append(f"{x:.6f} {y:.6f} {v}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Project-level checks
# ---------------------------------------------------------------------------
def _project_has_keypoints(db: Session, project_id: int) -> bool:
    """≥50% аннотаций проекта имеют скелет."""
    total = (db.query(func.count(Annotation.id))
               .join(ImageModel, Annotation.image_id == ImageModel.id)
               .filter(ImageModel.project_id == project_id,
                       ImageModel.is_deleted.is_(False))
               .scalar() or 0)
    if total == 0:
        return False
    with_kp = (db.query(func.count(func.distinct(Keypoint.annotation_id)))
                 .join(Annotation, Annotation.id == Keypoint.annotation_id)
                 .join(ImageModel, Annotation.image_id == ImageModel.id)
                 .filter(ImageModel.project_id == project_id,
                         ImageModel.is_deleted.is_(False))
                 .scalar() or 0)
    return (with_kp / total) >= 0.5
