# [PATCH:STAGE4_TRACK_SERVICE]
"""[STAGE4] Track service — вынесено из app.py для разрыва цикла app↔pipeline.

Содержит TRACK_STATE/TRACK_LOCK/TRACK_STOP/TRACK_THREAD/TRACK_EVENT,
_track_snapshot/_track_set/_track_worker.
"""
from __future__ import annotations

import gc
import logging
import os
import re
import threading
from collections import defaultdict

from sqlalchemy import func

from database import SessionLocal
from models import Video, ImageModel, Annotation
from logger import utcnow, log_status
from services.ml_service import _get_yolo_model
from services.tracker_service import TrackerState, process_frame_detections

log = logging.getLogger("db")

TRACK_STATE = {
    "status": "idle", "video_id": None,
    "total": 0, "done": 0, "failed": 0,
    "tracks": 0, "assignments": 0,
    "message": "", "started_at": None, "finished_at": None,
}
TRACK_LOCK = threading.Lock()
TRACK_STOP = threading.Event()
TRACK_THREAD = None
TRACK_EVENT = threading.Event()


def _db_commit_safe(db):
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning("DB commit failed: %s", e)
        raise


def _safe_error_message(e: Exception, context: str = "") -> str:
    name = type(e).__name__
    if "OperationalError" in name or "IntegrityError" in name or "ProgrammingError" in name:
        return f"{context}: ошибка БД" if context else "Ошибка БД"
    msg = re.sub(r'/[^\s]+/', '/…/', str(e))[:200]
    return f"{context}: {msg}" if context else msg


def _track_snapshot():
    with TRACK_LOCK:
        return dict(TRACK_STATE)


def _track_set(**kw):
    with TRACK_LOCK:
        TRACK_STATE.update(kw)
    TRACK_EVENT.set()


def _track_worker(video_id, project_id, model_path):
    global TRACK_THREAD
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            _track_set(status="error", message="Video not found",
                       finished_at=utcnow().isoformat())
            return
        frames = (db.query(ImageModel)
                    .filter(ImageModel.video_id == video_id,
                            ImageModel.is_deleted.is_(False))
                    .order_by(ImageModel.frame_index).all())
        if not frames:
            _track_set(status="error", message="No frames for this video",
                       finished_at=utcnow().isoformat())
            return
        max_aid = (db.query(func.max(Annotation.animal_id))
                     .join(ImageModel, Annotation.image_id == ImageModel.id)
                     .filter(ImageModel.project_id == project_id,
                             Annotation.animal_id.isnot(None))
                     .scalar() or 0)
        next_aid = int(max_aid) + 1
        anns_by_image = defaultdict(list)
        _frame_ids = [f.id for f in frames]
        for _i in range(0, len(_frame_ids), 500):
            _c = _frame_ids[_i:_i + 500]
            for a in (db.query(Annotation)
                        .filter(Annotation.image_id.in_(_c))
                        .order_by(Annotation.id).all()):
                anns_by_image[a.image_id].append(a)
        try:
            model = _get_yolo_model(model_path)
            model.predictor = None
        except Exception as e:
            _track_set(status="error",
                       message="Model load failed: %s" % _safe_error_message(e),
                       finished_at=utcnow().isoformat())
            return
        frame_paths = [im.path for im in frames if im.path and os.path.exists(im.path)]
        if not frame_paths:
            _track_set(status="error", message="No files on disk for this video",
                       finished_at=utcnow().isoformat())
            return
        _track_set(status="running", video_id=video_id, total=len(frame_paths),
                   done=0, failed=0, tracks=0, assignments=0,
                   started_at=utcnow().isoformat(), finished_at=None,
                   message="Tracking...")
        assignments = 0
        pending_commit = 0
        tracker_state = TrackerState()
        try:
            results_iter = model.track(source=frame_paths, stream=True,
                                        persist=True, tracker="bytetrack.yaml",
                                        conf=0.25, verbose=False)
        except Exception as e:
            _track_set(status="error",
                       message="Track init failed: %s" % _safe_error_message(e),
                       finished_at=utcnow().isoformat())
            return
        idx = -1
        try:
            for idx, r in enumerate(results_iter):
                if TRACK_STOP.is_set():
                    db.commit()
                    _track_set(status="stopped", message="Stopped by user",
                               finished_at=utcnow().isoformat())
                    return
                if idx >= len(frames):
                    break
                im = frames[idx]
                anns = anns_by_image.get(im.id, [])
                if not anns:
                    with TRACK_LOCK:
                        TRACK_STATE["done"] = idx + 1
                    TRACK_EVENT.set()
                    continue
                xyxy = tids = None
                try:
                    if r.boxes is not None and r.boxes.id is not None:
                        xyxy = r.boxes.xyxy.cpu().numpy()
                        tids = r.boxes.id.cpu().numpy()
                except Exception:
                    pass
                if xyxy is not None and tids is not None and len(xyxy) == len(tids):
                    W = im.width or 640
                    H = im.height or 640
                    frame_dets = []
                    for k in range(len(xyxy)):
                        try:
                            x1, y1, x2, y2 = xyxy[k].tolist()
                            track_id = int(tids[k])
                        except (TypeError, ValueError):
                            continue
                        if track_id <= 0:
                            continue
                        frame_dets.append({
                            "track_id": track_id,
                            "x": max(0.0, x1 / W), "y": max(0.0, y1 / H),
                            "w": max(0.0, min(1.0, (x2 - x1) / W)),
                            "h": max(0.0, min(1.0, (y2 - y1) / H)),
                        })
                    updates, next_aid, assigned = process_frame_detections(
                        frame_dets, anns, tracker_state, next_aid, im.path, idx)
                    assignments += assigned
                    pending_commit += len(updates)
                    if pending_commit >= 20:
                        _db_commit_safe(db)
                        pending_commit = 0
                with TRACK_LOCK:
                    TRACK_STATE["done"] = idx + 1
                    TRACK_STATE["tracks"] = len(tracker_state.track_to_aid)
                    TRACK_STATE["assignments"] = assignments
                TRACK_EVENT.set()
        finally:
            try:
                results_iter.close()
            except Exception:
                pass
        _db_commit_safe(db)
        _track_set(status="done", message="Tracking complete",
                   tracks=len(tracker_state.track_to_aid), assignments=assignments,
                   done=len(frame_paths), finished_at=utcnow().isoformat())
        log_status("info", "video",
                   "Трекинг видео #%d: кадров %d, треков %d, назначено %d"
                   % (video_id, len(frames), len(tracker_state.track_to_aid), assignments))
    except Exception as e:
        log.exception("track worker failed")
        try:
            db.rollback()
        except Exception:
            pass
        _track_set(status="error",
                   message=_safe_error_message(e),
                   finished_at=utcnow().isoformat())
    finally:
        try:
            db.close()
        except Exception:
            pass
        with TRACK_LOCK:
            TRACK_THREAD = None
        TRACK_EVENT.set()
        gc.collect()
# [/PATCH:STAGE4_TRACK_SERVICE]
