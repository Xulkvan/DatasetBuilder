"""routers/autolabel_batch.py — [PATCH:STAGE6-PART2-4.3] Batch autolabel."""
import threading, asyncio, json, logging
log = logging.getLogger('db')
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from database import get_db
from services.ml_service import (
    get_active_model_path, _get_yolo_model, _resolve_target_class_ids
)
from services.rate_limiter import _limiter_autolabel, _rate_limit
from config import DEFAULT_OBJECT_CLASS
from schemas import BatchAutolabelIn

import os
import gc
from models import Project, ImageModel, Annotation
from services.ml_service import (
    _autolabel_batch_predict, _save_autolabel_no_commit,
    _is_duplicate_box, _load_boxes_xywh
)
from services.image_service import _invalidate_stats_cache
from services.errors import _db_commit_safe
from logger import utcnow, log_status

router = APIRouter()

BATCH_STATE = {
    "status": "idle", "total": 0, "done": 0, "failed": 0,
    "current_id": None, "current_filename": "", "message": "",
    "started_at": None, "finished_at": None, "project_id": None,
    "added": 0, "skipped": 0, "mode": "add",  # V8.2.0
}
BATCH_LOCK = threading.Lock()
BATCH_STOP = threading.Event()
BATCH_THREAD = None
BATCH_EVENT = threading.Event()


def _norm_mode(m):
    return m if m in ("add", "replace") else "add"

def _batch_snapshot():
    with BATCH_LOCK:
        return dict(BATCH_STATE)

def _batch_worker(image_ids, model_path, project_id, mode="add", tta=False):
    global BATCH_THREAD
    from database import SessionLocal
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            with BATCH_LOCK:
                BATCH_STATE["status"] = "error"
                BATCH_STATE["message"] = "Проект не найден"
            log_status("error", "autolabel", "Батч: проект не найден")
            BATCH_EVENT.set()
            return
        target_label = project.object_class or DEFAULT_OBJECT_CLASS
        try:
            from ultralytics import YOLO
            model = YOLO(model_path)
        except Exception as e:
            with BATCH_LOCK:
                BATCH_STATE["status"] = "error"
                BATCH_STATE["message"] = f"Модель не загружена: {e}"
            log_status("error", "autolabel", f"Батч: модель не загружена: {e}")
            BATCH_EVENT.set()
            return
        target_ids = _resolve_target_class_ids(model, target_label)
        if not target_ids:
            msg = (f"Класс «{target_label}» не поддерживается активной моделью. "
                   f"Выбери OIV7 или обучи свою.")
            with BATCH_LOCK:
                BATCH_STATE["status"] = "error"
                BATCH_STATE["message"] = msg
            log_status("error", "autolabel", f"Батч: {msg}")
            BATCH_EVENT.set()
            return
        total = len(image_ids)
        with BATCH_LOCK:
            BATCH_STATE["total"] = total
            BATCH_STATE["added"] = 0
            BATCH_STATE["skipped"] = 0
            BATCH_STATE["mode"] = _norm_mode(mode)
        log_status("info", "autolabel",
                   f"Батч-авторазметка: {total} изобр., класс «{target_label}»")
        BATCH_EVENT.set()

        batch_size = 16
        try:
            import torch
            if not torch.cuda.is_available():
                batch_size = 4
        except Exception:
            batch_size = 4

        for chunk_start in range(0, total, batch_size):
            if BATCH_STOP.is_set():
                db.rollback()
                with BATCH_LOCK:
                    BATCH_STATE["status"] = "stopped"
                    BATCH_STATE["message"] = "Остановлено пользователем"
                log_status("warning", "autolabel", "Батч-авторазметка остановлена")
                BATCH_EVENT.set()
                return

            chunk_ids = image_ids[chunk_start:chunk_start+batch_size]
            imgs = db.query(ImageModel).filter(ImageModel.id.in_(chunk_ids)).all()
            if not imgs:
                with BATCH_LOCK:
                    BATCH_STATE["done"] += len(chunk_ids)
                    BATCH_STATE["failed"] += len(chunk_ids)
                BATCH_EVENT.set()
                continue

            valid_imgs = []
            paths = []
            for img in imgs:
                if img and os.path.exists(img.path):
                    valid_imgs.append(img)
                    paths.append(img.path)
                else:
                    with BATCH_LOCK:
                        BATCH_STATE["done"] += 1
                        BATCH_STATE["failed"] += 1
                    BATCH_EVENT.set()

            if not paths:
                continue

            with BATCH_LOCK:
                BATCH_STATE["current_id"] = valid_imgs[0].id
                BATCH_STATE["current_filename"] = f"{valid_imgs[0].filename} (+{len(paths)-1})"
            BATCH_EVENT.set()

            try:
                W_list = [img.width or 640 for img in valid_imgs]
                H_list = [img.height or 640 for img in valid_imgs]
                batch_results = _autolabel_batch_predict(paths, model, W_list, H_list, target_ids, target_label, tta=tta)

                chunk_added = 0
                chunk_skipped = 0
                for img, raw_new in zip(valid_imgs, batch_results):
                    iid = img.id
                    if _norm_mode(mode) == "add":
                        existing = _load_boxes_xywh(db, iid)
                        unique, skipped_n = [], 0
                        for d in raw_new:
                            if any(_is_duplicate_box(d, e) for e in existing):
                                skipped_n += 1
                            else:
                                unique.append(d)
                        for a in unique:
                            db.add(Annotation(
                                image_id=iid, x=a["x"], y=a["y"],
                                w=a["w"], h=a["h"], label=target_label,
                                confidence=a["confidence"], is_frozen=False,
                            ))
                        chunk_added += len(unique)
                        chunk_skipped += skipped_n
                    else:
                        _save_autolabel_no_commit(db, iid, raw_new, target_label)
                        chunk_added += len(raw_new)

                _db_commit_safe(db)

                with BATCH_LOCK:
                    BATCH_STATE["added"] += chunk_added
                    BATCH_STATE["skipped"] += chunk_skipped
                    BATCH_STATE["done"] += len(valid_imgs)
            except Exception as e:
                log.warning("batch chunk fail: %s", e)
                db.rollback()
                with BATCH_LOCK:
                    BATCH_STATE["done"] += len(valid_imgs)
                    BATCH_STATE["failed"] += len(valid_imgs)
            BATCH_EVENT.set()

        with BATCH_LOCK:
            BATCH_STATE["status"] = "done"
            BATCH_STATE["message"] = "Готово"
            BATCH_STATE["current_id"] = None
            BATCH_STATE["current_filename"] = ""
        log_status("success", "autolabel",
                   f"Батч-авторазметка завершена: "
                   f"{BATCH_STATE['done'] - BATCH_STATE['failed']} ok, "
                   f"{BATCH_STATE['failed']} ошибок")
    finally:
        db.close()
        with BATCH_LOCK:
            BATCH_STATE["finished_at"] = utcnow().isoformat()
            BATCH_THREAD = None
        BATCH_EVENT.set()
        _invalidate_stats_cache(project_id)
        gc.collect()


@router.post("/api/autolabel/batch/start")
def batch_autolabel_start(payload: BatchAutolabelIn, db: Session = Depends(get_db)):
    global BATCH_THREAD
    _rate_limit(_limiter_autolabel, "local", "Слишком много запусков батча")
    with BATCH_LOCK:
        if BATCH_STATE["status"] == "running":
            raise HTTPException(409, {"key": "error.batchRunning", "fallback": "Батч уже идёт"})
        ids = [int(x) for x in (payload.image_ids or [])]
        if not ids:
            raise HTTPException(400, {"key": "error.emptyImageIds", "fallback": "Пустой список image_ids"})
        BATCH_STATE["status"] = "starting"
    model_path = get_active_model_path(db)
    if not model_path:
        with BATCH_LOCK:
            BATCH_STATE["status"] = "idle"
        raise HTTPException(501, {"key": "error.noModel", "fallback": "Активная модель не найдена"})
    if payload.project_id:
        proj = db.query(Project).filter(Project.id == payload.project_id).first()
        if proj:
            try:
                model = _get_yolo_model(model_path)
                if not _resolve_target_class_ids(model, str(proj.object_class or DEFAULT_OBJECT_CLASS)):
                    with BATCH_LOCK:
                        BATCH_STATE["status"] = "idle"
                    raise HTTPException(
                        422,
                        f"Класс «{proj.object_class}» не поддерживается активной моделью. "
                        f"Выбери OIV7 или обучи свою."
                    )
            except HTTPException:
                raise
            except Exception:
                log.exception("batch: cannot verify model classes")
    BATCH_STOP.clear()
    with BATCH_LOCK:
        BATCH_STATE.update({
            "status": "running", "total": len(ids), "done": 0, "failed": 0,
            "current_id": None, "current_filename": "",
            "message": "Запуск...",
            "started_at": utcnow().isoformat(), "finished_at": None,
            "project_id": payload.project_id,
            "added": 0, "skipped": 0,
            "mode": _norm_mode(payload.mode),
        })
    BATCH_EVENT.set()
    t = threading.Thread(target=_batch_worker,
                         args=(ids, model_path, payload.project_id,
                               _norm_mode(payload.mode)), daemon=True)
    BATCH_THREAD = t
    t.start()
    return {"status": "started", "total": len(ids)}


@router.get("/api/autolabel/batch/status")
def batch_autolabel_status():
    return _batch_snapshot()


@router.post("/api/autolabel/batch/stop")
def batch_autolabel_stop():
    with BATCH_LOCK:
        if BATCH_STATE["status"] != "running":
            return {"status": "not_running"}
        BATCH_STATE["message"] = "Останавливаю..."
    BATCH_STOP.set()
    BATCH_EVENT.set()
    return {"status": "stopping"}


@router.get("/api/autolabel/batch/events")
async def batch_autolabel_events():
    async def gen():
        snap = _batch_snapshot()
        yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
        last = json.dumps(snap, ensure_ascii=False)
        while True:
            await asyncio.get_event_loop().run_in_executor(None, BATCH_EVENT.wait, 1.0)
            BATCH_EVENT.clear()
            snap = _batch_snapshot()
            payload = json.dumps(snap, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if snap["status"] != "running":
                break
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ============================================================================
# V8.8.0: трекинг кадров через ByteTrack.
# ============================================================================

# [PATCH:STAGE4_APP_TRACK_BLOCK]
# TRACK_STATE/TRACK_LOCK/TRACK_STOP/TRACK_THREAD/TRACK_EVENT
# и _track_worker/_track_snapshot/_track_set перенесены в
# services/track_service.py (см. импорт в шапке).
# [/PATCH:STAGE4_APP_TRACK_BLOCK]
# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------
