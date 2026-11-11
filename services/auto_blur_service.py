"""[FIX:v1341-backend] Auto-blur persons/plates на новых изображениях."""
from __future__ import annotations

import json
import logging
import os
import threading

log = logging.getLogger("db")

_EXECUTOR = None
_EXECUTOR_LOCK = threading.Lock()
_MODEL = None
_MODEL_LOCK = threading.Lock()


def _get_executor():
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            from concurrent.futures import ThreadPoolExecutor
            _EXECUTOR = ThreadPoolExecutor(max_workers=2,
                                            thread_name_prefix="auto-blur")
        return _EXECUTOR


def _get_blur_model():
    """Загружает yolov8n.pt (COCO). Stage 5.4 — без silent download."""
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        import os as _os
        allow_download = (_os.getenv("AUTO_BLUR_ALLOW_DOWNLOAD", "0").strip().lower()
                          in ("1", "true", "yes"))
        from config import MODEL_DIR as _MD
        # Ищем локальный yolov8n.pt; при отсутствии — по env решаем.
        _candidates = [
            _os.path.join(_MD, "yolov8n.pt"),
            "yolov8n.pt",
        ]
        _model_arg = next((p for p in _candidates if _os.path.isfile(p)), None)
        if _model_arg is None and not allow_download:
            log.warning(
                "auto-blur: yolov8n.pt not found; download disabled "
                "(set AUTO_BLUR_ALLOW_DOWNLOAD=1 to allow)."
            )
            return None
        try:
            import torch
            torch.set_num_threads(1)
            from ultralytics import YOLO
            _MODEL = YOLO(_model_arg or "yolov8n.pt")
            log.info("auto-blur: model loaded from %s", _model_arg or "yolov8n.pt")
        except Exception:
            log.exception("auto-blur: cannot load model")
            _MODEL = None
        return _MODEL


def schedule_auto_blur(image_id: int, project_id: int) -> None:
    """Ставит задачу в фоновый пул. Тихо игнорирует ошибки."""
    try:
        _get_executor().submit(_run_auto_blur, image_id, project_id)
    except Exception:
        log.exception("schedule_auto_blur failed")


def _run_auto_blur(image_id: int, project_id: int) -> None:
    from database import SessionLocal
    from models import Project, ImageModel, BlurRegion
    from config import AUTO_BLUR_COCO_MAP
    from services.image_service import _iou_xywh
    db = SessionLocal()
    try:
        proj = (db.query(Project)
                  .filter(Project.id == project_id).first())
        if not proj or not bool(getattr(proj, "auto_blur_enabled", False)):
            return
        img = (db.query(ImageModel)
                 .filter(ImageModel.id == image_id).first())
        if not img or not os.path.exists(img.path):
            return
        # Если у изображения уже есть ручные/авто blur-region'ы — дополняем,
        # не перезаписываем.
        # запоминаем существующие регионы для IoU-dedup
        existing_regions = (db.query(BlurRegion)
                              .filter(BlurRegion.image_id == image_id).all())
        model = _get_blur_model()
        if model is None:
            return
        try:
            raw_classes = proj.auto_blur_classes or '["person"]'
            wanted = json.loads(raw_classes)
            if not isinstance(wanted, list):
                wanted = ["person"]
        except Exception:
            wanted = ["person"]
        class_ids = [AUTO_BLUR_COCO_MAP[c] for c in wanted
                     if c in AUTO_BLUR_COCO_MAP]
        if not class_ids:
            return
        W = img.width or 640
        H = img.height or 640
        try:
            results = model(img.path, classes=class_ids,
                            conf=0.35, verbose=False)
        except Exception:
            log.exception("auto-blur inference failed for image %d", image_id)
            return
        added = 0
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                try:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                except Exception:
                    continue
                bw = (x2 - x1) / W
                bh = (y2 - y1) / H
                # Отсеиваем ложное «всё изображение».
                if bw * bh > 0.95 or bw <= 0 or bh <= 0:
                    continue
                _new_reg = {
                    "x": max(0.0, x1 / W),
                    "y": max(0.0, y1 / H),
                    "w": max(0.0, min(1.0, bw)),
                    "h": max(0.0, min(1.0, bh)),
                }
                # IoU > 0.5 с existing → skip
                _is_dup = False
                for _er in existing_regions:
                    _er_dict = {"x": _er.x, "y": _er.y, "w": _er.w, "h": _er.h}
                    if _iou_xywh(_new_reg, _er_dict) > 0.5:
                        _is_dup = True
                        break
                if _is_dup:
                    continue
                db.add(BlurRegion(image_id=image_id, **_new_reg))
                added += 1
        if added:
            db.commit()
            log.info("auto-blur: %d regions on image %d (%d existed)",
                     added, image_id, len(existing_regions))
    except Exception:
        log.exception("auto_blur worker failed")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()
