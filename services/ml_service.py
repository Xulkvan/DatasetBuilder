"""YOLO model loading, caching, and autolabel logic."""
import os
import gc
import logging
import threading
from collections import OrderedDict, defaultdict
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Project, ImageModel, Annotation, Setting, Keypoint
from config import (
    SETTING_ACTIVE_MODEL, SETTING_ACTIVE_POSE_MODEL, SETTING_USE_SINGLE_MODEL,
    CONF_THRESHOLD, DEDUP_IOU_THRESHOLD, MODEL_DIR
)
from services.image_service import _iou_xywh, dedup_boxes
from services.file_service import _safe_model_path

log = logging.getLogger("db")

class ModelCache:
    def __init__(self, max_size=2, ttl_seconds=600):
        import time
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        import time
        with self._lock:
            if key not in self._cache: return None
            val, ts = self._cache[key]
            if time.time() - ts > self.ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            self._cache[key] = (val, time.time())
            return val

    def put(self, key, value):
        import time
        with self._lock:
            if key in self._cache: del self._cache[key]
            self._cache[key] = (value, time.time())
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def clear(self):
        with self._lock: self._cache.clear()
        try:
            import torch
            if torch.cuda.is_available(): torch.cuda.empty_cache()
        except Exception: pass
        gc.collect()

    def cleanup(self):
        import time
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
                if torch.cuda.is_available(): torch.cuda.empty_cache()
            except Exception: pass
            gc.collect()

_YOLO_CACHE = ModelCache(max_size=2, ttl_seconds=600)

def _clear_yolo_cache():
    _YOLO_CACHE.clear()

def _get_yolo_model(model_path: str):
    m = _YOLO_CACHE.get(model_path)
    if m is not None: return m
    try:
        from ultralytics import YOLO
        m = YOLO(model_path)
        _YOLO_CACHE.put(model_path, m)
        return m
    except Exception as e:
        err_str = str(e).lower()
        if "out of memory" in err_str or "cuda" in err_str or "defaultcpuallocator" in err_str:
            _YOLO_CACHE.clear()
            try:
                import torch
                if torch.cuda.is_available(): torch.cuda.empty_cache()
            except Exception: pass
            raise RuntimeError("Недостаточно памяти для загрузки модели. Попробуйте закрыть другие приложения или использовать модель полегче (nano).")
        raise e

def _is_pose_model_name(name: str) -> bool:
    # [STAGE3:ONNX-ML-SERVICE]
    base = (name or "").lower()
    if base.endswith(".onnx"):
        stem = base[:-5]
    elif base.endswith(".pt"):
        stem = base[:-3]
    else:
        return False
    return stem.endswith("-pose") or stem.endswith("_pose")

def _is_single_model_mode(db) -> bool:
    row = db.query(Setting).filter(Setting.key == SETTING_USE_SINGLE_MODEL).first()
    return (row.value if row else "1") == "1"

def _find_first_pose_in_dir() -> str:
    from config import MODEL_DIR
    if os.path.isdir(MODEL_DIR):
        for f in sorted(os.listdir(MODEL_DIR)):
            if (f.endswith(".pt") or f.endswith(".onnx")) \
                    and _is_pose_model_name(f):
                return os.path.join(MODEL_DIR, f)
    return None

def get_active_pose_model_path(db):
    if _is_single_model_mode(db):
        row = db.query(Setting).filter(Setting.key == SETTING_ACTIVE_MODEL).first()
        active = row.value if row else ""
        if active and _is_pose_model_name(active):
            try:
                p = _safe_model_path(active)
                if os.path.exists(p): return p
            except Exception: pass
        return _find_first_pose_in_dir()
    else:
        row = db.query(Setting).filter(Setting.key == SETTING_ACTIVE_POSE_MODEL).first()
        name = row.value if row else ""
        if name:
            try:
                p = _safe_model_path(name)
                if os.path.exists(p): return p
            except Exception: pass
        return _find_first_pose_in_dir()

def get_active_model_path(db):
    row = db.query(Setting).filter(Setting.key == SETTING_ACTIVE_MODEL).first()
    name = row.value if row else ""
    if name:
        try:
            p = _safe_model_path(name)
            if os.path.exists(p): return p
        except Exception: pass

    from config import MODEL_DIR
    default_path = os.path.join(MODEL_DIR, "pig.pt")
    if os.path.exists(default_path): return default_path

    if os.path.isdir(MODEL_DIR):
        for f in sorted(os.listdir(MODEL_DIR)):
            if f.endswith(".pt") or f.endswith(".onnx"):
                return os.path.join(MODEL_DIR, f)
    return None

def _resolve_target_class_ids(model, object_class: str) -> set:
    names = getattr(model, "names", {}) or {}
    target = (object_class or "").strip().lower()
    if not target: return set()
    out = set()
    for cid, cname in names.items():
        try: cn = str(cname).strip().lower()
        except Exception: continue
        if cn == target:
            try: out.add(int(cid))
            except (TypeError, ValueError): continue
    return out

def _read_model_class_names(model) -> list:
    names = getattr(model, "names", {}) or {}
    result = []
    for cid, cname in names.items():
        try: cn = str(cname).strip()
        except Exception: continue
        if cn: result.append(cn)
    seen = set()
    unique = []
    for n in result:
        key = n.lower()
        if key in seen: continue
        seen.add(key)
        unique.append(n)
    unique.sort(key=lambda s: s.lower())
    return unique


def _autolabel_batch_predict(img_paths: list, model, W: list | int, H: list | int, target_class_ids: set, target_label: str, conf: float = None, tta: bool = False):
    """Батч-предсказание для списка путей (изолированный вызов модели)."""
    if conf is None: conf = CONF_THRESHOLD
    batch_raw = []
    for i, path in enumerate(img_paths):
        w = W[i] if isinstance(W, (list, tuple)) else W
        h = H[i] if isinstance(H, (list, tuple)) else H
        try:
            # Изоляция: отключаем кэш-эффекты при вызове из потока
            results = model(path, conf=conf, verbose=False, augment=bool(tta))
            raw = []
            for r in results:
                for box in r.boxes:
                    try: cls_id = int(box.cls[0])
                    except Exception: cls_id = 0
                    if not target_class_ids or cls_id not in target_class_ids: continue  # [STAGE4:FIX-AUTOLABEL-FALLBACK]
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    try: bconf = float(box.conf[0])
                    except Exception: bconf = None
                    raw.append({"x": x1 / w, "y": y1 / h, "w": (x2 - x1) / w, "h": (y2 - y1) / h, "label": target_label, "confidence": bconf})
            batch_raw.append(dedup_boxes(raw))
            print(f"[BATCH DEBUG] Image: {path} -> Found: {len(raw)} boxes")
        except Exception as e:
            log.warning("batch predict failed for %s: %s", path, e)
            print(f"[BATCH DEBUG] Image: {path} -> ERROR: {e}")
            batch_raw.append([])
    return batch_raw

def _autolabel_image_predict(img_path: str, model, W: int, H: int, target_class_ids: set, target_label: str, conf: float = None, tta: bool = False):
    if conf is None: conf = CONF_THRESHOLD
    results = model(img_path, conf=conf, verbose=False, augment=bool(tta))
    raw = []
    for r in results:
        for box in r.boxes:
            try: cls_id = int(box.cls[0])
            except Exception: cls_id = 0
            if target_class_ids and cls_id not in target_class_ids: continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            try: bconf = float(box.conf[0])
            except Exception: bconf = None
            raw.append({"x": x1 / W, "y": y1 / H, "w": (x2 - x1) / W, "h": (y2 - y1) / H, "label": target_label, "confidence": bconf})
    return dedup_boxes(raw)

def _save_autolabel_no_commit(db, image_id: int, anns: list, label: str):
    # [PATCH:STAGE1-ORPHAN-KEYPOINTS]
    _ann_ids = [row.id for row in db.query(Annotation.id).filter(
        Annotation.image_id == image_id,
        Annotation.is_frozen.is_(False)).all()]
    if _ann_ids:
        db.query(Keypoint).filter(Keypoint.annotation_id.in_(_ann_ids)).delete(synchronize_session=False)
    db.query(Annotation).filter(Annotation.image_id == image_id, Annotation.is_frozen.is_(False)).delete(synchronize_session=False)
    if anns:
        db.add_all([Annotation(image_id=image_id, x=a["x"], y=a["y"], w=a["w"], h=a["h"], label=label, confidence=a["confidence"], is_frozen=False, behavior=None, animal_id=None) for a in anns])

def _save_autolabel(db, image_id: int, anns: list, label: str):
    _save_autolabel_no_commit(db, image_id, anns, label)
    db.commit()

def _is_duplicate_box(a: dict, b: dict, iou_thr: float = 0.5, center_dist_thr: float = 0.05) -> bool:
    if _iou_xywh(a, b) > iou_thr: return True
    ax, ay = a["x"] + a["w"] / 2, a["y"] + a["h"] / 2
    bx, by = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 < center_dist_thr

def _load_boxes_xywh(db, image_id: int) -> list:
    rows = db.query(Annotation.x, Annotation.y, Annotation.w, Annotation.h).filter(Annotation.image_id == image_id).all()
    return [{"x": r.x, "y": r.y, "w": r.w, "h": r.h} for r in rows]

def _load_annotations(db, image_id: int) -> list:
    from collections import defaultdict
    from models import Keypoint
    rows = db.query(Annotation).filter(Annotation.image_id == image_id).order_by(Annotation.id).all()
    ann_ids = [r.id for r in rows]
    kps_by_ann = defaultdict(list)
    if ann_ids:
        for kp in db.query(Keypoint).filter(Keypoint.annotation_id.in_(ann_ids)).all():
            kps_by_ann[kp.annotation_id].append({"name": kp.name, "x": kp.x, "y": kp.y, "visibility": kp.visibility})
    return [{"id": r.id, "x": r.x, "y": r.y, "w": r.w, "h": r.h, "label": r.label, "confidence": r.confidence, "frozen": bool(r.is_frozen), "behavior": r.behavior, "animal_id": r.animal_id, "keypoints": kps_by_ann.get(r.id, [])} for r in rows]


def _autolabel_image_with_model(db, img, model, project, conf=None, tta=False, mode="add"):
    target_label = project.object_class or "pig"
    target_ids = _resolve_target_class_ids(model, target_label)
    if not target_ids:
        raise ValueError(f"Класс «{target_label}» не поддерживается активной моделью.")
    raw_new = _autolabel_image_predict(img.path, model, img.width, img.height, target_ids, target_label, conf, tta)

    if (mode or "add") == "add":
        existing = _load_boxes_xywh(db, img.id)
        unique, skipped = [], 0
        for d in raw_new:
            if any(_is_duplicate_box(d, e) for e in existing): skipped += 1
            else: unique.append(d)
        if unique:
            db.add_all([Annotation(image_id=img.id, x=a["x"], y=a["y"], w=a["w"], h=a["h"], label=target_label, confidence=a["confidence"], is_frozen=False, behavior=None, animal_id=None) for a in unique])
            db.commit()
        return {"boxes": _load_annotations(db, img.id), "added": len(unique), "skipped": skipped, "total": len(existing) + len(unique), "mode": "add"}

    _save_autolabel(db, img.id, raw_new, target_label)
    return {"boxes": _load_annotations(db, img.id), "added": len(raw_new), "skipped": 0, "total": len(raw_new), "mode": "replace"}

def _apply_pose_detection_to_anns(db, img, results, only_empty=True, iou_threshold=0.30, kp_conf_threshold=0.4) -> dict:
    # [FIX:v1341-backend] Кастомная схема применяется здесь.
    from config import get_keypoint_schema_for_project
    _schema = get_keypoint_schema_for_project(db, getattr(img, "project_id", None))
    n_points = len(_schema)
    kp_names = [k[0] for k in _schema]

    anns = db.query(Annotation).filter(Annotation.image_id == img.id).order_by(Annotation.id).all()
    if not anns: return {"saved_annotations": 0, "saved_keypoints": 0, "skipped_existing": 0, "unmatched_detections": 0}

    existing_kp_anns = set()
    if only_empty:
        existing_kp_anns = {row.annotation_id for row in db.query(Keypoint.annotation_id).filter(Keypoint.annotation_id.in_([a.id for a in anns])).distinct().all()}

    detections = []
    for r in results:
        if r.keypoints is None: continue
        try:
            xyxy = r.boxes.xyxy.cpu().numpy()
            kp_xy = r.keypoints.xy.cpu().numpy()
            kp_conf = r.keypoints.conf.cpu().numpy()
        except Exception: continue
        for k in range(len(xyxy)):
            x1, y1, x2, y2 = xyxy[k].tolist()
            W, H = img.width or 640, img.height or 640
            bbox = {"x": max(0.0, x1 / W), "y": max(0.0, y1 / H), "w": max(0.0, min(1.0, (x2 - x1) / W)), "h": max(0.0, min(1.0, (y2 - y1) / H))}
            kps = []
            for i in range(min(n_points, len(kp_xy[k]))):
                px, py = kp_xy[k][i].tolist()
                pc = float(kp_conf[k][i]) if i < len(kp_conf[k]) else 0.0
                kps.append({"name": kp_names[i], "x": max(0.0, min(1.0, px / W)), "y": max(0.0, min(1.0, py / H)), "visibility": 1.0 if pc >= kp_conf_threshold else 0.0, "conf": pc})
            detections.append({"bbox": bbox, "keypoints": kps})

    if not detections: return {"saved_annotations": 0, "saved_keypoints": 0, "skipped_existing": 0, "unmatched_detections": 0}

    saved_anns, saved_kps, skipped = 0, 0, 0
    for a in anns:
        if only_empty and a.id in existing_kp_anns: skipped += 1; continue
        a_box = {"x": a.x, "y": a.y, "w": a.w, "h": a.h}
        best, best_iou = None, 0.0
        for d in detections:
            iou = _iou_xywh(a_box, d["bbox"])
            if iou > best_iou: best_iou = iou; best = d
        if best is None or best_iou < iou_threshold: continue
        if not only_empty: db.query(Keypoint).filter(Keypoint.annotation_id == a.id).delete(synchronize_session=False)
        for kp in best["keypoints"]:
            db.add(Keypoint(annotation_id=a.id, name=kp["name"], x=kp["x"], y=kp["y"], visibility=kp["visibility"]))
            saved_kps += 1
        saved_anns += 1
    if saved_anns: db.commit()
    return {"saved_annotations": saved_anns, "saved_keypoints": saved_kps, "skipped_existing": skipped, "unmatched_detections": len(detections)}

def _count_annotations_with_skeleton(db, project_id: int) -> int:
    return int(db.query(func.count(func.distinct(Keypoint.annotation_id))).join(Annotation, Annotation.id == Keypoint.annotation_id).join(ImageModel, Annotation.image_id == ImageModel.id).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)).scalar() or 0)


# === Model classes cache ===
_MODEL_CLASSES_CACHE: dict = {}
_MODEL_CLASSES_LOCK = threading.Lock()

def _get_model_classes_cached(model_name: str):
    with _MODEL_CLASSES_LOCK:
        if model_name in _MODEL_CLASSES_CACHE:
            return _MODEL_CLASSES_CACHE[model_name]
    try:
        path = _safe_model_path(model_name)
    except Exception:
        return None
    if not os.path.exists(path):
        return None
    try:
        from ultralytics import YOLO
        m = YOLO(path)
        names = getattr(m, "names", {}) or {}
        classes = set()
        for _, v in names.items():
            try:
                classes.add(str(v).strip().lower())
            except Exception:
                continue
        with _MODEL_CLASSES_LOCK:
            _MODEL_CLASSES_CACHE[model_name] = classes
        try:
            del m
        except Exception:
            pass
        gc.collect()
        return classes
    except Exception:
        log.exception("load model classes failed: %s", model_name)
        return None

def _invalidate_model_classes_cache(name=None):
    with _MODEL_CLASSES_LOCK:
        if name is None:
            _MODEL_CLASSES_CACHE.clear()
        else:
            _MODEL_CLASSES_CACHE.pop(name, None)


# ============================================================================
# [STAGE3:uncertainty-queue] Очередь неразмеченных изображений для Active Learning.
# ============================================================================
def get_uncertainty_queue(db, project_id: int, limit: int = 50) -> list:
    """Возвращает неразмеченные изображения, ранжированные по неуверенности YOLO.

    Логика:
      * для каждого изображения без аннотаций прогоняется активная YOLO-модель
        (conf=0.10);
      * вычисляется max_conf по всем детекциям и (если есть) энтропия по классам;
      * приоритет отдаётся тем, у кого max_conf попал в диапазон [0.3, 0.6]
        (модель "не уверена"), затем — ближайшим к середине диапазона.
    """
    from models import ImageModel, Annotation, Project
    model_path = get_active_model_path(db)
    if not model_path:
        return []
    try:
        model = _get_yolo_model(model_path)
    except Exception:
        return []
    project = (db.query(Project)
                 .filter(Project.id == project_id).first())
    target_label = (project.object_class if project else None) or "pig"
    target_ids = _resolve_target_class_ids(model, target_label)

    annotated_subq = db.query(Annotation.image_id).distinct()
    candidates = (db.query(ImageModel)
                    .filter(ImageModel.project_id == project_id,
                            ImageModel.is_deleted.is_(False),
                            ~ImageModel.id.in_(annotated_subq))
                    .limit(max(200, limit * 4)).all())

    items = []
    for im in candidates:
        max_conf = 0.0
        entropy = None
        try:
            results = model(im.path, conf=0.10, verbose=False)
        except Exception:
            results = []
        for r in results:
            try:
                if r.boxes is not None and len(r.boxes) > 0:
                    confs = r.boxes.conf.cpu().numpy().tolist()
                    if confs:
                        mc = float(max(confs))
                        if mc > max_conf:
                            max_conf = mc
                probs = getattr(r, "probs", None)
                if probs is not None:
                    try:
                        import numpy as _np
                        p = probs.data.cpu().numpy()
                        ent = -float((p * _np.log(p + 1e-9)).sum())
                        if entropy is None or ent > entropy:
                            entropy = ent
                    except Exception:
                        pass
            except Exception:
                continue
        in_band = 0.3 <= max_conf <= 0.6
        priority = (1.0 - abs(max_conf - 0.45)) if in_band else 0.0
        items.append({
            "image_id": im.id,
            "filename": im.filename,
            "max_conf": round(max_conf, 4),
            "entropy": None if entropy is None else round(entropy, 4),
            "in_uncertainty_band": in_band,
            "_priority": priority,
        })
    items.sort(key=lambda x: x["_priority"], reverse=True)
    for it in items:
        it.pop("_priority", None)
    return items[:limit]
# [/STAGE3:uncertainty-queue]

# [STAGE3:ONNX-ML-SERVICE-END]
