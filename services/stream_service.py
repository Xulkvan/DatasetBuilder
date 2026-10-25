"""[FIX:v1341-backend] RTSP-стримы — переработано."""
from __future__ import annotations

import logging
import threading
import time
import uuid

log = logging.getLogger("db")

_STREAMS: dict = {}
_LOCK = threading.Lock()


def _utcnow():
    from logger import utcnow
    return utcnow()


def _key(project_id: int, url: str) -> str:
    return f"{project_id}:{url}"


def start_stream_worker(stream_url: str, project_id: int,
                        fps: float = 1.0, stream_id: int = None) -> dict:
    """Запускает фоновый поток чтения RTSP. Возвращает {status}."""
    key = _key(project_id, stream_url)
    with _LOCK:
        cur = _STREAMS.get(key)
        if cur and cur.get("active"):
            return {"status": "already_running", "stream_url": stream_url}
    stop_event = threading.Event()
    with _LOCK:
        _STREAMS[key] = {
            "stop_event": stop_event,
            "active": True,
            "stream_id": stream_id,
            "started_at": _utcnow().isoformat(),
        }
    t = threading.Thread(
        target=_stream_worker,
        args=(stream_url, project_id, float(fps), stop_event, stream_id),
        daemon=True,
        name=f"stream-{project_id}",
    )
    t.start()
    return {"status": "started", "stream_url": stream_url, "fps": float(fps)}


def stop_stream_worker(stream_url: str, project_id: int) -> dict:
    key = _key(project_id, stream_url)
    with _LOCK:
        s = _STREAMS.get(key)
        if not s:
            return {"status": "not_running"}
        s["stop_event"].set()
        s["active"] = False
    return {"status": "stopping"}


def list_active_streams() -> list:
    with _LOCK:
        return [
            {"key": k,
             "stream_id": v.get("stream_id"),
             "active": v.get("active"),
             "started_at": v.get("started_at")}
            for k, v in _STREAMS.items()
        ]


def _mark_stream_inactive(stream_id):
    if stream_id is None:
        return
    try:
        from database import SessionLocal
        from models import Stream
        db = SessionLocal()
        try:
            st = (db.query(Stream)
                    .filter(Stream.id == stream_id).first())
            if st is not None and st.is_active:
                st.is_active = False
                db.commit()
                log.info("stream #%d marked inactive", stream_id)
        finally:
            db.close()
    except Exception:
        log.exception("mark_stream_inactive failed")


def _iou(a, b):
    ax1, ay1 = a["x"], a["y"]; ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx1, by1 = b["x"], b["y"]; bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / ua if ua > 0 else 0.0


def _track_update(state: dict, dets: list, iou_thr: float = 0.3) -> list:
    """Простейший IoU-трекер. Возвращает dets с добавленным animal_id."""
    active = state.get("active", [])  # [{bbox, aid, misses}]
    next_aid = state.get("next_aid", 1)
    out = []
    used = set()
    for det in dets:
        best_i = -1
        best_iou = 0.0
        for i, tr in enumerate(active):
            if i in used:
                continue
            v = _iou(tr["bbox"], det)
            if v > best_iou:
                best_iou = v
                best_i = i
        if best_i >= 0 and best_iou >= iou_thr:
            tr = active[best_i]
            tr["bbox"] = det
            tr["misses"] = 0
            used.add(best_i)
            det["animal_id"] = tr["aid"]
        else:
            det["animal_id"] = next_aid
            active.append({"bbox": det, "aid": next_aid, "misses": 0})
            used.add(len(active) - 1)
            next_aid += 1
        out.append(det)
    for i, tr in enumerate(active):
        if i not in used:
            tr["misses"] = tr.get("misses", 0) + 1
    state["active"] = [tr for tr in active if tr.get("misses", 0) <= 5]
    state["next_aid"] = next_aid
    return out


def _stream_worker(stream_url: str, project_id: int, fps: float,
                   stop_event: threading.Event, stream_id: int) -> None:
    try:
        import cv2
    except ImportError:
        log.error("stream: opencv (cv2) not installed")
        _mark_stream_inactive(stream_id)
        return

    from database import SessionLocal
    from models import ImageModel, Project, Annotation
    from services.ml_service import (
        get_active_model_path, _get_yolo_model, _resolve_target_class_ids,
    )
    from config import UPLOAD_DIR, FIXED_SIZE, LETTERBOX_FILL
    from services.file_service import letterbox
    from services.image_service import _queue_thumb
    from services.auto_blur_service import schedule_auto_blur
    from PIL import Image

    db = SessionLocal()
    try:
        proj = (db.query(Project)
                  .filter(Project.id == project_id).first())
        if not proj:
            log.error("stream: project %d not found", project_id)
            _mark_stream_inactive(stream_id)
            return
        model_path = get_active_model_path(db)
        model = None
        target_ids = set()
        target_label = proj.object_class or "pig"
        if model_path:
            try:
                model = _get_yolo_model(model_path)
                target_ids = _resolve_target_class_ids(model, target_label)
            except Exception:
                log.exception("stream: cannot load YOLO model")
                model = None

        try:
            cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
        except Exception:
            cap = cv2.VideoCapture(stream_url)
        if not cap.isOpened():
            log.error("stream: cannot open %s", stream_url)
            _mark_stream_inactive(stream_id)
            return
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        frame_interval = 1.0 / max(float(fps), 0.1)
        frame_counter = 0
        fail_streak = 0
        last_ts = 0.0
        track_state = {"active": [], "next_aid": 1}

        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                fail_streak += 1
                if fail_streak >= 5:
                    log.warning("stream: %d consecutive read failures, abort",
                                fail_streak)
                    break
                time.sleep(0.5)
                continue
            fail_streak = 0
            now = time.monotonic()
            if (now - last_ts) < frame_interval:
                continue
            last_ts = now
            frame_counter += 1
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil = Image.fromarray(rgb)
                pil = letterbox(pil, FIXED_SIZE, LETTERBOX_FILL)
                fname = f"stream_{uuid.uuid4().hex}.jpg"
                path = f"{UPLOAD_DIR}/{fname}"
                pil.save(path, "JPEG", quality=90)
                im = ImageModel(
                    project_id=project_id,
                    filename=fname,
                    path=path,
                    width=FIXED_SIZE[0],
                    height=FIXED_SIZE[1],
                    is_deleted=False,
                    phash=None,
                    is_hard=False,
                    video_id=None,
                    frame_index=frame_counter,
                    created_at=_utcnow(),
                    file_size=None,
                    timestamp_sec=frame_counter / max(float(fps), 0.1),
                    is_stream_frame=True,
                )
                db.add(im)
                db.commit()
                db.refresh(im)
                _queue_thumb(im.id, im.path)
                try:
                    schedule_auto_blur(im.id, project_id)
                except Exception:
                    pass

                if model is not None and target_ids:
                    try:
                        results = model(im.path, conf=0.25, verbose=False)
                        dets = []
                        for r in results:
                            if r.boxes is None:
                                continue
                            for box in r.boxes:
                                try:
                                    cid = int(box.cls[0])
                                except Exception:
                                    continue
                                if cid not in target_ids:
                                    continue
                                x1, y1, x2, y2 = box.xyxy[0].tolist()
                                bconf = float(box.conf[0])
                                dets.append({
                                    "x": max(0.0, x1 / FIXED_SIZE[0]),
                                    "y": max(0.0, y1 / FIXED_SIZE[1]),
                                    "w": max(0.0, min(1.0, (x2 - x1) / FIXED_SIZE[0])),
                                    "h": max(0.0, min(1.0, (y2 - y1) / FIXED_SIZE[1])),
                                    "confidence": bconf,
                                })
                        tracked = _track_update(track_state, dets)
                        for d in tracked:
                            db.add(Annotation(
                                image_id=im.id,
                                x=d["x"], y=d["y"], w=d["w"], h=d["h"],
                                label=target_label,
                                confidence=d.get("confidence"),
                                is_frozen=False,
                                animal_id=d.get("animal_id"),
                            ))
                        db.commit()
                    except Exception:
                        db.rollback()
                        log.exception("stream: inference failed")
            except Exception:
                log.exception("stream: frame processing failed")
                try:
                    db.rollback()
                except Exception:
                    pass
        try:
            cap.release()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass
        with _LOCK:
            _STREAMS.pop(_key(project_id, stream_url), None)
        _mark_stream_inactive(stream_id)
