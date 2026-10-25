"""[STAGE2:api_v2] API v2 — Bearer auth, async tasks."""
from __future__ import annotations

import os
import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Project, ImageModel, Annotation
from logger import utcnow, log_status

router = APIRouter(prefix="/api/v2", tags=["api_v2"])

# In-memory реестр фоновых задач (простой, не переживает рестарт процесса)
_TASKS: dict = {}
_TASKS_LOCK = threading.Lock()
TASK_TTL_SEC = 3600


def _cleanup_tasks():
    now = time.time()
    with _TASKS_LOCK:
        stale = [tid for tid, t in _TASKS.items()
                 if now - t.get("created_ts", now) > TASK_TTL_SEC
                 and t.get("status") != "running"]
        for tid in stale:
            _TASKS.pop(tid, None)


def _mk_task(kind: str, project_id: int) -> str:
    tid = uuid.uuid4().hex
    with _TASKS_LOCK:
        _TASKS[tid] = {
            "task_id": tid, "kind": kind, "project_id": project_id,
            "status": "queued", "progress": 0.0, "message": "",
            "created_ts": time.time(),
            "started_at": utcnow().isoformat(), "finished_at": None,
            "result": None, "error": None,
        }
    return tid


def _update_task(tid: str, **kw):
    with _TASKS_LOCK:
        if tid in _TASKS:
            _TASKS[tid].update(kw)


def require_api_key(request: Request):
    """Проверка Bearer если API_KEY задан в окружении."""
    expected = (os.getenv("API_KEY") or "").strip()
    if not expected:
        return  # auth disabled
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, {"key": "error.unauthorized",
                                 "fallback": "Missing Bearer token"})
    token = auth[7:].strip()
    if token != expected:
        raise HTTPException(403, {"key": "error.forbidden",
                                 "fallback": "Invalid API key"})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/projects", dependencies=[Depends(require_api_key)])
def v2_list_projects(db: Session = Depends(get_db)):
    rows = (db.query(Project)
              .filter(Project.is_deleted.is_(False))
              .order_by(Project.id).all())
    counts = dict(db.query(ImageModel.project_id, func.count(ImageModel.id))
                    .filter(ImageModel.is_deleted.is_(False))
                    .group_by(ImageModel.project_id).all())
    return [{"id": p.id, "name": p.name,
             "object_class": p.object_class or "pig",
             "images_count": int(counts.get(p.id, 0)),
             "random_seed": getattr(p, "random_seed", 42)}
            for p in rows]


@router.get("/projects/{project_id}/images", dependencies=[Depends(require_api_key)])
def v2_list_images(project_id: int, offset: int = 0, limit: int = 100,
                   db: Session = Depends(get_db)):
    limit = max(1, min(1000, int(limit)))
    rows = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False))
              .order_by(ImageModel.id)
              .offset(max(0, offset)).limit(limit).all())
    return {"items": [{"id": r.id, "filename": r.filename,
                       "width": r.width, "height": r.height,
                       "video_id": r.video_id, "frame_index": r.frame_index}
                      for r in rows],
            "offset": offset, "limit": limit}


@router.post("/projects/{project_id}/autolabel",
             status_code=202, dependencies=[Depends(require_api_key)])
def v2_autolabel_async(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    _cleanup_tasks()
    tid = _mk_task("autolabel", project_id)

    def worker():
        from database import SessionLocal
        from services.ml_service import (get_active_model_path, _get_yolo_model,
                                         _autolabel_image_with_model)
        _update_task(tid, status="running", message="autolabel start")
        s = SessionLocal()
        try:
            mp = get_active_model_path(s)
            if not mp:
                _update_task(tid, status="error", error="no active model",
                             finished_at=utcnow().isoformat())
                return
            model = _get_yolo_model(mp)
            pr = s.query(Project).filter(Project.id == project_id).first()
            imgs = (s.query(ImageModel)
                     .filter(ImageModel.project_id == project_id,
                             ImageModel.is_deleted.is_(False)).all())
            total = len(imgs) or 1
            for i, im in enumerate(imgs):
                try:
                    _autolabel_image_with_model(s, im, model, pr, mode="add")
                except Exception as e:
                    log_status("warning", "autolabel",
                               f"v2 autolabel img {im.id}: {e}")
                _update_task(tid, progress=(i + 1) / total * 100.0,
                             message=f"autolabel {i+1}/{total}")
            _update_task(tid, status="done", progress=100.0,
                         finished_at=utcnow().isoformat(),
                         result={"images": len(imgs)})
        except Exception as e:
            _update_task(tid, status="error", error=str(e),
                         finished_at=utcnow().isoformat())
        finally:
            s.close()

    threading.Thread(target=worker, daemon=True,
                     name=f"v2-autolabel-{tid[:6]}").start()
    return {"task_id": tid, "status": "queued",
            "poll_url": f"/api/v2/tasks/{tid}"}


@router.post("/projects/{project_id}/train",
             status_code=202, dependencies=[Depends(require_api_key)])
def v2_train_async(project_id: int, payload: dict | None = None,
                   db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    _cleanup_tasks()
    payload = payload or {}
    tid = _mk_task("train", project_id)
    epochs = int(payload.get("epochs", 50))
    task = payload.get("task", "detect")

    def worker():
        from database import SessionLocal
        from services.train_service import _save_training_metadata
        from app import (
            prepare_training_dataset,
            _run_training_thread,
        )
        _update_task(tid, status="running", message="training start")
        s = SessionLocal()
        try:
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            from config import RUNS_DIR
            run_dir = os.path.join(RUNS_DIR, f"train_{run_id}")
            os.makedirs(run_dir, exist_ok=True)
            if task == "pose":
                from services.train_service import prepare_training_dataset_pose
                yaml_path = prepare_training_dataset_pose(s, project_id, run_dir)
            else:
                yaml_path = prepare_training_dataset(s, project_id, run_dir)
            base_model = payload.get("base_model", "yolov8n.pt")
            from pathlib import Path as _P
            args = ["yolo", task, "train",
                    f"data={yaml_path}", f"model={base_model}",
                    f"epochs={epochs}"]
            _run_training_thread(args, run_dir, run_id, payload.get("model_name", ""))
            _update_task(tid, status="done", progress=100.0,
                         finished_at=utcnow().isoformat(),
                         result={"run_id": run_id})
        except Exception as e:
            _update_task(tid, status="error", error=str(e),
                         finished_at=utcnow().isoformat())
        finally:
            s.close()

    threading.Thread(target=worker, daemon=True,
                     name=f"v2-train-{tid[:6]}").start()
    return {"task_id": tid, "status": "queued",
            "poll_url": f"/api/v2/tasks/{tid}"}


@router.get("/tasks/{task_id}", dependencies=[Depends(require_api_key)])
def v2_task_status(task_id: str):
    with _TASKS_LOCK:
        t = _TASKS.get(task_id)
        if not t:
            raise HTTPException(404, {"key": "error.taskNotFound",
                                     "fallback": "Task not found"})
        return dict(t)


# нужно для datetime в worker (импорт внутри)
from datetime import datetime  # noqa: E402
