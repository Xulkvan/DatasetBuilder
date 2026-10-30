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
from config import get_keypoint_schema_for_project  # [PATCH:STAGE1_API_V2_KP_IMPORT]

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
@router.get("/projects", dependencies=[Depends(require_api_key)], summary="List projects", description="Returns all non-deleted projects with image counts.")
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


@router.get("/projects/{project_id}/images", dependencies=[Depends(require_api_key)], summary="List project images", description="Paginated list of images for a project.")
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
             status_code=202, dependencies=[Depends(require_api_key)], summary="Start async autolabel", description="Kicks off a background autolabel task; returns task_id for polling.")
def v2_autolabel_async(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    schema = get_keypoint_schema_for_project(db, project_id)
    kp_names = [k[0] for k in schema] # [PATCH:FIX_CUSTOM_KP_V2_SCHEMA]
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
             status_code=202, dependencies=[Depends(require_api_key)], summary="Start async training", description="Kicks off a background training task; returns task_id for polling.")
def v2_train_async(project_id: int, payload: dict | None = None,
                   db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    schema = get_keypoint_schema_for_project(db, project_id)
    kp_names = [k[0] for k in schema] # [PATCH:FIX_CUSTOM_KP_V2_SCHEMA]
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


@router.get("/tasks/{task_id}", dependencies=[Depends(require_api_key)], summary="Task status", description="Returns status / progress / result of a background task.")
def v2_task_status(task_id: str):
    with _TASKS_LOCK:
        t = _TASKS.get(task_id)
        if not t:
            raise HTTPException(404, {"key": "error.taskNotFound",
                                     "fallback": "Task not found"})
        return dict(t)


# нужно для datetime в worker (импорт внутри)
from datetime import datetime  # noqa: E402


# ============================================================================
# [STAGE1:api-v2-extensions] Дополнительные эндпоинты для B2B.
# ============================================================================
import os as _os
import uuid as _uuid
from fastapi import UploadFile as _UploadFile, File as _File


@router.post("/projects/{project_id}/images",
             dependencies=[Depends(require_api_key)], summary="Upload image", description="Upload one image via multipart/form-data. Deduplicates by pHash.")
def v2_upload_image(project_id: int,
                    file: _UploadFile = _File(...),
                    db: Session = Depends(get_db)):
    """Загрузка одного изображения (multipart/form-data, поле `file`)."""
    from config import UPLOAD_DIR, FIXED_SIZE, LETTERBOX_FILL
    from services.file_service import (
        _detect_image_format, _open_image_safe, letterbox,
        sanitize_display_name, make_unique_filename,
    )
    from services.image_service import (
        phash_hex, find_duplicate, _queue_thumb, _invalidate_stats_cache,
    )
    proj = (db.query(Project)
              .filter(Project.id == project_id,
                      Project.is_deleted.is_(False)).first())
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    schema = get_keypoint_schema_for_project(db, project_id)
    kp_names = [k[0] for k in schema] # [PATCH:FIX_CUSTOM_KP_V2_SCHEMA]
    data = file.file.read(50 * 1024 * 1024 + 1)
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "File too large (>50 MB)")
    if not _detect_image_format(data):
        raise HTTPException(400, {"key": "error.invalidImage",
                                 "fallback": "Invalid image format"})
    img = _open_image_safe(data).convert("RGB")
    img = letterbox(img, FIXED_SIZE, LETTERBOX_FILL)
    fname = f"{_uuid.uuid4().hex}.jpg"
    path = _os.path.join(UPLOAD_DIR, fname)
    img.save(path, "JPEG", quality=95)
    try:
        ph = phash_hex(path)
    except Exception:
        ph = ""
    dup = find_duplicate(db, project_id, ph)
    if dup:
        try:
            _os.remove(path)
        except OSError:
            pass
        raise HTTPException(409, f"Duplicate: {dup.filename}")
    original_name = sanitize_display_name(file.filename or fname, fallback=fname)
    unique_name = make_unique_filename(db, project_id, original_name)
    try:
        fsize = _os.path.getsize(path)
    except OSError:
        fsize = len(data)
    im = ImageModel(project_id=project_id, filename=unique_name, path=path,
                    width=FIXED_SIZE[0], height=FIXED_SIZE[1],
                    is_deleted=False, phash=ph or None, is_hard=False,
                    created_at=utcnow(), file_size=fsize)
    db.add(im)
    db.commit()
    db.refresh(im)
    _queue_thumb(im.id, im.path)
    # [FIX:v1341-backend]
    try:
        from services.auto_blur_service import schedule_auto_blur
        schedule_auto_blur(im.id, project_id)
    except Exception:
        pass
    _invalidate_stats_cache(project_id)
    return {"id": im.id, "filename": im.filename,
            "width": im.width, "height": im.height}


@router.get("/projects/{project_id}/annotations",
            dependencies=[Depends(require_api_key)], summary="COCO annotations JSON", description="Returns the entire project annotations as COCO JSON.")
def v2_export_coco(project_id: int, db: Session = Depends(get_db)):
    """Экспорт всей разметки проекта в формате COCO JSON."""
    from models import Keypoint
    from config import KEYPOINT_NAMES, get_keypoint_schema_for_project # [PATCH:FIX_CUSTOM_KP_V2_IMPORT]
    proj = (db.query(Project)
              .filter(Project.id == project_id,
                      Project.is_deleted.is_(False)).first())
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    schema = get_keypoint_schema_for_project(db, project_id)
    kp_names = [k[0] for k in schema] # [PATCH:FIX_CUSTOM_KP_V2_SCHEMA]
    images = (db.query(ImageModel)
                .filter(ImageModel.project_id == project_id,
                        ImageModel.is_deleted.is_(False)).all())
    coco_images = []
    coco_annotations = []
    ann_id = 1
    for im in images:
        coco_images.append({
            "id": im.id, "file_name": im.filename,
            "width": im.width, "height": im.height,
        })
        anns = (db.query(Annotation)
                  .filter(Annotation.image_id == im.id)
                  .order_by(Annotation.id).all())
        for a in anns:
            W = im.width or 640
            H = im.height or 640
            ann = {
                "id": ann_id, "image_id": im.id, "category_id": 1,
                "bbox": [a.x * W, a.y * H, a.w * W, a.h * H],
                "area": a.w * W * a.h * H, "iscrowd": 0,
            }
            if a.behavior:
                ann["behavior"] = a.behavior
            if a.animal_id is not None:
                ann["animal_id"] = a.animal_id
            kps = (db.query(Keypoint)
                     .filter(Keypoint.annotation_id == a.id).all())
            if kps:
                kp_map = {k.name: k for k in kps}
                flat = []
                for nm in kp_names:
                    kp = kp_map.get(nm)
                    if kp:
                        flat.extend([kp.x * W, kp.y * H,
                                     2 if (kp.visibility or 0) >= 0.5 else 1])
                    else:
                        flat.extend([0, 0, 0])
                ann["keypoints"] = flat
                ann["num_keypoints"] = sum(
                    1 for i in range(2, len(flat), 3) if flat[i] > 0)
            coco_annotations.append(ann)
            ann_id += 1
    return {
        "info": {
            "description": f"DatasetBuilder export: {proj.name}",
            "date_created": utcnow().isoformat(),
        },
        "images": coco_images,
        "annotations": coco_annotations,
        "categories": [{"id": 1, "name": proj.object_class or "pig"}],
    }


@router.post("/projects/{project_id}/export/{format}",
             dependencies=[Depends(require_api_key)], summary="Export dataset", description="Returns a download_url for the requested format (yolo|coco).")
def v2_export_dataset(project_id: int, format: str,
                      db: Session = Depends(get_db)):
    """Запуск экспорта датасета. Возвращает download_url существующего роутера."""
    fmt = (format or "").lower()
    if fmt not in ("yolo", "coco"):
        raise HTTPException(400,
                            f"Unsupported format: {format}. Use 'yolo' or 'coco'.")
    proj = (db.query(Project)
              .filter(Project.id == project_id,
                      Project.is_deleted.is_(False)).first())
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    schema = get_keypoint_schema_for_project(db, project_id)
    kp_names = [k[0] for k in schema] # [PATCH:FIX_CUSTOM_KP_V2_SCHEMA]
    return {
        "status": "ok",
        "format": fmt,
        "download_url": f"/api/projects/{project_id}/export/{fmt}?naming=numbered&split=none",
        "annotations_url": f"/api/v2/projects/{project_id}/annotations",
    }
# [/STAGE1:api-v2-extensions]

# [FIX:v1341-backend]


# ============================================================================
# [STAGE1:API-V2-EXT] Unified export endpoint (yolo_pose | coco | parquet)
# ============================================================================
@router.get("/projects/{project_id}/export",
            dependencies=[Depends(require_api_key)],
            summary="Unified dataset export",
            description="Returns download_url for the requested format: "
                        "yolo_pose (YOLO with keypoints), "
                        "coco (COCO JSON), parquet (Parquet+CSV zip).")
def v2_export_unified(project_id: int, format: str = "coco",
                      db: Session = Depends(get_db)):
    proj = (db.query(Project)
              .filter(Project.id == project_id,
                      Project.is_deleted.is_(False)).first())
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    schema = get_keypoint_schema_for_project(db, project_id)
    kp_names = [k[0] for k in schema] # [PATCH:FIX_CUSTOM_KP_V2_SCHEMA]
    fmt = (format or "coco").lower()
    # [FIX-STAGE2:API-V2-FORCE-POSE] разделяем yolo и yolo_pose:
    # для yolo_pose форсируем pose-формат через force_pose=true
    if fmt == "yolo_pose":
        url = f"/api/projects/{project_id}/export/yolo?naming=numbered&split=none&force_pose=true"
        out_fmt = "yolo_pose"
    elif fmt == "yolo":
        url = f"/api/projects/{project_id}/export/yolo?naming=numbered&split=none"
        out_fmt = "yolo"
    # [/FIX-STAGE2:API-V2-FORCE-POSE]
    elif fmt == "coco":
        url = f"/api/projects/{project_id}/export/coco?naming=numbered&split=none"
        out_fmt = "coco"
    elif fmt == "parquet":
        url = f"/api/projects/{project_id}/export/parquet"
        out_fmt = "parquet"
    else:
        raise HTTPException(400,
                            f"Unsupported format: {format}. "
                            f"Use yolo_pose | coco | parquet.")
    return {"download_url": url, "format": out_fmt}
# [/STAGE1:API-V2-EXT]
