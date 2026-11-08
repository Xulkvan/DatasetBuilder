"""routers/videos.py — Stage 3.11 (track endpoints moved from app.py)."""
import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Project, Video, ImageModel, Annotation
from services.ml_service import get_active_model_path
from services.track_service import (
    TRACK_STATE, TRACK_LOCK, TRACK_STOP, TRACK_EVENT,
    _track_snapshot, _track_worker,
)
from logger import utcnow
import logging

log = logging.getLogger("db")
router = APIRouter()


@router.post("/api/videos/{video_id}/track")
def video_track_start(video_id: int, db: Session = Depends(get_db)):
    # [STAGE3.11] thin adapter, body moved from app.py
    import services.track_service as _ts_mod
    with TRACK_LOCK:
        if TRACK_STATE["status"] in ("running", "starting"):
            raise HTTPException(409, "Трекинг уже идёт")
        TRACK_STATE["status"] = "starting"
        TRACK_STATE["message"] = "Starting..."
    try:
        from services.pipeline_service import PIPELINE_STATE as _PS
        if _PS.get("status") in ("running", "stopping"):
            raise HTTPException(409, "Идёт полная разметка (pipeline). Дождитесь окончания.")
    except HTTPException:
        raise
    except Exception:
        pass
    video = db.query(Video).filter(Video.id == video_id,
                                    Video.is_deleted.is_(False)).first()
    if not video:
        raise HTTPException(404, "Видео не найдено")
    project = db.query(Project).filter(Project.id == video.project_id).first()
    if not project:
        raise HTTPException(404, "Проект не найден")
    frames_count = (db.query(func.count(ImageModel.id))
                      .filter(ImageModel.video_id == video_id,
                              ImageModel.is_deleted.is_(False))
                      .scalar() or 0)
    if frames_count == 0:
        raise HTTPException(400, "У этого видео нет кадров")
    model_path = get_active_model_path(db)
    if not model_path:
        raise HTTPException(501, "Нет активной YOLO-модели. Загрузи или обучи.")
    TRACK_STOP.clear()
    with TRACK_LOCK:
        TRACK_STATE.update({
            "status": "running", "video_id": video_id,
            "total": int(frames_count), "done": 0, "failed": 0,
            "tracks": 0, "assignments": 0,
            "message": "Starting...",
            "started_at": utcnow().isoformat(), "finished_at": None,
        })
    TRACK_EVENT.set()
    import threading as _th
    t = _th.Thread(target=_track_worker,
                   args=(video_id, video.project_id, model_path),
                   daemon=True, name="tracker")
    _ts_mod.TRACK_THREAD = t
    t.start()
    return {"status": "started", "total": int(frames_count)}


@router.get("/api/videos/{video_id}/track/status")
def video_track_status(video_id: int):
    return _track_snapshot()


@router.post("/api/videos/{video_id}/track/stop")
def video_track_stop(video_id: int):
    with TRACK_LOCK:
        if TRACK_STATE["status"] != "running":
            return {"status": "not_running"}
        TRACK_STATE["message"] = "Stopping..."
    TRACK_STOP.set()
    TRACK_EVENT.set()
    return {"status": "stopping"}


@router.get("/api/videos/{video_id}/track/events")
async def video_track_events(video_id: int):
    async def gen():
        snap = _track_snapshot()
        yield "data: " + json.dumps(snap, ensure_ascii=False) + "\n\n"
        last = json.dumps(snap, ensure_ascii=False)
        while True:
            await asyncio.get_event_loop().run_in_executor(
                None, TRACK_EVENT.wait, 1.0)
            TRACK_EVENT.clear()
            snap = _track_snapshot()
            payload = json.dumps(snap, ensure_ascii=False)
            if payload != last:
                yield "data: " + payload + "\n\n"
                last = payload
            if snap["status"] not in ("running",):
                break
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/api/videos/{video_id}/track/metrics")
def video_track_metrics(video_id: int, db: Session = Depends(get_db)):
    try:
        from eval_tracker import compute_mota, compute_idf1
    except ImportError as e:
        raise HTTPException(501, f"eval_tracker.py unavailable: {e}")
    from collections import defaultdict
    video = (db.query(Video)
               .filter(Video.id == video_id, Video.is_deleted.is_(False))
               .first())
    if not video:
        raise HTTPException(404, "Video not found")
    frames = (db.query(ImageModel)
                .filter(ImageModel.video_id == video_id,
                        ImageModel.is_deleted.is_(False))
                .order_by(ImageModel.frame_index).all())
    if not frames:
        raise HTTPException(400, "No frames for this video")
    frame_ids = [f.id for f in frames]
    id_to_fidx = {f.id: (f.frame_index if f.frame_index is not None else f.id)
                  for f in frames}
    gt_frames = defaultdict(list)
    pred_frames = defaultdict(list)
    anns = (db.query(Annotation)
              .filter(Annotation.image_id.in_(frame_ids))
              .all())
    for a in anns:
        fidx = id_to_fidx.get(a.image_id, a.image_id)
        entry = {"track_id": int(a.animal_id) if a.animal_id is not None else 0,
                 "x": float(a.x), "y": float(a.y),
                 "w": float(a.w), "h": float(a.h)}
        if a.confidence is None:
            gt_frames[fidx].append(entry)
        else:
            pred_frames[fidx].append(entry)
    total_gt = sum(len(v) for v in gt_frames.values())
    total_pred = sum(len(v) for v in pred_frames.values())
    if total_gt == 0:
        return {"video_id": video_id, "mota": None, "idf1": None,
                "gt_count": 0, "pred_count": total_pred,
                "reason": "no_manual_ground_truth",
                "hint": "Нужны ручные аннотации (confidence=null) как ground truth"}
    try:
        mota = float(compute_mota(gt_frames, pred_frames))
        idf1 = float(compute_idf1(gt_frames, pred_frames))
    except Exception as e:
        log.exception("track metrics failed")
        raise HTTPException(500, f"Metrics computation failed: {e}")
    return {"video_id": video_id, "mota": round(mota, 4),
            "idf1": round(idf1, 4), "gt_count": total_gt,
            "pred_count": total_pred,
            "frames_with_gt": len(gt_frames),
            "frames_with_pred": len(pred_frames)}
