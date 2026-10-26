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
    """Загружает yolov8n.pt (COCO, умеет person/car/plate)."""
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        try:
            import torch
            torch.set_num_threads(1) # [PERF:1-thread]
            from ultralytics import YOLO
            _MODEL = YOLO("yolov8n.pt")
            log.info("auto-blur: yolov8n.pt loaded")
        except Exception:
            log.exception("auto-blur: cannot load yolov8n.pt")
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
        existing = (db.query(BlurRegion)
                      .filter(BlurRegion.image_id == image_id)
                      .count())
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
                db.add(BlurRegion(
                    image_id=image_id,
                    x=max(0.0, x1 / W),
                    y=max(0.0, y1 / H),
                    w=max(0.0, min(1.0, bw)),
                    h=max(0.0, min(1.0, bh)),
                ))
                added += 1
        if added:
            db.commit()
            log.info("auto-blur: %d regions on image %d (%d existed)",
                     added, image_id, existing)
    except Exception:
        log.exception("auto_blur worker failed")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()
