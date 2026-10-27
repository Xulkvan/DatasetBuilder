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


def _track_update(state: dict, dets: list, iou_thr: float = 0.3,
                  image_path: str = None, stream_id: int = None) -> list:
    """Простейший IoU-трекер + кросс-камерный ReID.

    Параметры image_path и stream_id нужны для ReID:
      * при потере трека (misses > 5) эмбеддинг его bbox кладётся
        в GLOBAL_TRACKS (services.reid_service);
      * при появлении нового трека сначала ищем совпадение в
        GLOBAL_TRACKS по cosine distance < 0.15 (т.е. cos sim > 0.85),
        и только потом создаём новый animal_id.
    """
    # Ленивые импорты: избегаем циклической зависимости при старте приложения
    from services.reid_service import global_put, global_match
    from services.tracker_service import _crop_embed

    active = state.get("active", [])  # [{bbox, aid, misses, last_image_path}]
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
            # Трек продолжается
            tr = active[best_i]
            tr["bbox"] = det
            tr["misses"] = 0
            if image_path:
                tr["last_image_path"] = image_path
            used.add(best_i)
            det["animal_id"] = tr["aid"]
        else:
            # [STAGE2:REID] Новый трек — сначала пытаемся cross-camera match
            matched_aid = None
            # [FIX-STAGE:REID-FAST] быстрый выход, если в пуле нет
            # потерянных треков — избегаем дорогого _crop_embed
            # (PIL + file IO) на каждой новой детекции.
            if image_path and _global_pool_not_empty():
                try:
                    emb = _crop_embed(image_path, det)
                except Exception:
                    emb = []
                if emb:
                    matched_aid, _sim = global_match(emb, max_dist=0.15)
                    if matched_aid is not None:
                        log.info(
                            "cross-camera ReID hit: cam=%s aid=%s sim=%.3f",
                            stream_id, matched_aid, _sim,
                        )
            if matched_aid is not None:
                det["animal_id"] = matched_aid
                active.append({
                    "bbox": det, "aid": matched_aid,
                    "misses": 0, "last_image_path": image_path,
                })
                # [FIX-STAGE2:NEXT-AID] не допускаем коллизии ID:
                # matched_aid пришёл из GLOBAL_TRACKS и мог быть > next_aid
                next_aid = max(next_aid, int(matched_aid) + 1)
            else:
                det["animal_id"] = next_aid
                active.append({
                    "bbox": det, "aid": next_aid,
                    "misses": 0, "last_image_path": image_path,
                })
                next_aid += 1
            used.add(len(active) - 1)
        out.append(det)

    # Инкремент misses для треков, которых не было в кадре
    for i, tr in enumerate(active):
        if i not in used:
            tr["misses"] = tr.get("misses", 0) + 1

    # [STAGE2:REID] Отделяем потерянные треки → GLOBAL_TRACKS, живые → active
    new_active = []
    for tr in active:
        if tr.get("misses", 0) > 5:
            try:
                _p = tr.get("last_image_path") or image_path
                if _p:
                    _emb = _crop_embed(_p, tr["bbox"])
                    if _emb:
                        global_put(tr["aid"], _emb, camera_id=stream_id)
                        log.info(
                            "cross-camera ReID: track aid=%s lost → saved (cam=%s)",
                            tr["aid"], stream_id,
                        )
            except Exception:
                pass
        else:
            new_active.append(tr)
    state["active"] = new_active
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

    import torch
    torch.set_num_threads(1) # [PERF:1-thread]
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
        # [FIX-STAGE2:NEXT-AID-INIT] продолжаем нумерацию с максимума,
        # чтобы не коллидировать с уже существующими animal_id проекта
        try:
            from sqlalchemy import func as _sa_func
            _max_aid = (db.query(_sa_func.max(Annotation.animal_id))
                          .join(ImageModel, Annotation.image_id == ImageModel.id)
                          .filter(ImageModel.project_id == project_id,
                                  Annotation.animal_id.isnot(None))
                          .scalar() or 0)
        except Exception:
            _max_aid = 0
        track_state = {"active": [], "next_aid": int(_max_aid) + 1}
        # [/FIX-STAGE2:NEXT-AID-INIT]

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
                        tracked = _track_update(track_state, dets, image_path=im.path, stream_id=stream_id)
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
