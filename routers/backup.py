"""routers/backup.py — [PATCH:STAGE6-PART2-4.4]"""
import os
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Project
from services.backup_service import create_backup
from services.bulk_transfer_service import _bulk_transfer
from services.errors import _safe_error_message
from schemas import BulkMoveCopyIn
from logger import log_status

import logging  # [PATCH:REFACTOR-FIX]
log = logging.getLogger("db")  # [PATCH:REFACTOR-FIX]

# Full project backup export
from services.auth_service import get_current_user, require_permission
from services.project_access import check_project_access
from services.backup_service import export_full_project


router = APIRouter()

@router.post("/api/projects/{project_id}/backup", deprecated=True)
def backup_project(project_id: int, db: Session = Depends(get_db)):
    # [PATCH:STAGE2-F-11] логика вынесена в services.backup_service.create_backup
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    try:
        zip_path, meta = create_backup(db, project_id,
                                        prefix="backup_project")
    except ValueError:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    except Exception as e:
        log_status("error", "backup",
                   f"Бэкап проекта #{project_id} не удался: {e}")
        raise HTTPException(500, f"Бэкап не удался: {_safe_error_message(e)}")
    size = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0
    log_status("success", "backup",
               f"Бэкап проекта «{proj.name}» (id={project_id}, "
               f"класс={meta.get('object_class')}): "
               f"{meta.get('images_count', 0)} фото, "
               f"{size/1024/1024:.1f} МБ → {os.path.basename(zip_path)}")
    return {
        "status": "ok", "filename": os.path.basename(zip_path),
        "path": zip_path, "size": size,
        "images_count": meta.get("images_count", 0),
        "tags_count": meta.get("tags_count", 0),
        "annotations_count": meta.get("annotations_count", 0),
    }


@router.get("/api/projects/{project_id}/backup/download/{filename}", deprecated=True)
def download_backup(project_id: int, filename: str, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    if filename != os.path.basename(filename):
        raise HTTPException(400, "Некорректное имя файла")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Некорректное имя файла")
    if not filename.startswith(f"backup_project_{project_id}_"):
        raise HTTPException(400, "Файл не относится к этому проекту")
    if not filename.endswith(".zip"):
        raise HTTPException(400, "Ожидается .zip")
    # [FIX:STAGE2-backup-dl-dyn] Читаем config.BACKUP_DIR динамически:
    # после importlib.reload(config) в тестах локальная копия BACKUP_DIR
    # в app.py устаревает, и download ищет файл в старой папке.
    import config as _cfg_dl
    _backup_dir = _cfg_dl.BACKUP_DIR
    path = os.path.join(_backup_dir, filename)
    if os.path.islink(path):
        raise HTTPException(400, "Символические ссылки не поддерживаются")
    real = os.path.realpath(path)
    root = os.path.realpath(_backup_dir)
    if not real.startswith(root + os.sep):
        raise HTTPException(400, {"key": "error.invalidPath", "fallback": "Некорректный путь"})
    # [FIX:STAGE2-dl-fallback] На Windows realpath может расходиться с
    # фактическим путём (junction / %TEMP% redirect): create_backup
    # писал по `path`, а download проверял `real`. Пробуем сначала path
    # (куда реально записали), затем real (резолвнутый).
    _candidate = None
    if os.path.exists(path):
        _candidate = path
    elif os.path.exists(real):
        _candidate = real
    if _candidate is None:
        try:
            log.warning(
                "backup download: file not found. "
                "BACKUP_DIR=%r filename=%r path=%r real=%r",
                _backup_dir, filename, path, real,
            )
        except Exception:
            pass
        raise HTTPException(404, "Файл не найден")
    return FileResponse(_candidate, filename=filename, media_type="application/zip")

# [PATCH:STAGE3_ANNS_WITH_KP_CHUNKED]

@router.post("/api/images/bulk_move_to_project")
def bulk_move(payload: BulkMoveCopyIn, db: Session = Depends(get_db)):
    return _bulk_transfer(db, payload, copy=False)


@router.post("/api/images/bulk_copy_to_project")
def bulk_copy(payload: BulkMoveCopyIn, db: Session = Depends(get_db)):
    return _bulk_transfer(db, payload, copy=True)

@router.get("/api/projects/{project_id}/export/full",
            dependencies=[Depends(require_permission("dataset.export"))])
def export_full(
    project_id: int,
    include_videos: bool = True,
    include_versions: bool = True,
    include_blur_regions: bool = True,
    include_behavior_validations: bool = True,
    include_streams: bool = False,
    include_webhooks: bool = False,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # require_permission проверяет RBAC по роли.
    # check_project_access — object-level: annotator видит только свои.
    check_project_access(db, project_id, user)
    try:
        result = export_full_project(
            db, project_id,
            include_videos=include_videos,
            include_versions=include_versions,
            include_blur_regions=include_blur_regions,
            include_behavior_validations=include_behavior_validations,
            include_streams=include_streams,
            include_webhooks=include_webhooks,
        )
    except ValueError:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                  "fallback": "Project not found"})
    except Exception as e:
        log_status("error", "backup", f"export_full failed: {e}")
        raise HTTPException(500, {
            "key": "error.backupFailed",
            "fallback": f"Backup failed: {_safe_error_message(e)}",
        })
    log_status("success", "backup",
               f"Full backup project #{project_id} "
               f"({result['zip_size']} bytes)")
    return FileResponse(
        result["zip_path"],
        media_type="application/zip",
        filename=os.path.basename(result["zip_path"]),
    )


from fastapi import UploadFile, File
from config import MAX_IMPORT_BYTES
from services.backup_service import import_full_project
from services.rate_limiter import _limiter_import, _rate_limit


@router.post("/api/projects/import/full",
             dependencies=[Depends(require_permission("project.manage"))])
def import_full(file: UploadFile = File(...),
                user: dict = Depends(get_current_user),
                db: Session = Depends(get_db)):
    # require_permission("project.manage") ограничивает admin/manager.
    # check_project_access не вызывается: проект создаётся, а не читается.
    #
    # _limiter_import (fail_mode="open", 5/600s) — тяжёлая операция,
    # degraded-open допустим: при multi-worker лимит не работает, но
    # это не brute-force.
    _rate_limit(_limiter_import, "import_full",
                {"key": "error.rateLimitedImport",
                 "fallback": "Слишком много импортов."})

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, {"key": "error.invalidZip",
                                  "fallback": "Ожидается .zip"})

    import tempfile
    total = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        tmp_path = tmp.name
        try:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_IMPORT_BYTES:
                    raise HTTPException(413, {
                        "key": "error.payloadTooLarge",
                        "fallback": f"Архив больше "
                                    f"{MAX_IMPORT_BYTES // (1024*1024)} МБ",
                    })
                tmp.write(chunk)
        except HTTPException:
            tmp.close()
            os.remove(tmp_path)
            raise
    try:
        return import_full_project(db, tmp_path)
    except ValueError as e:
        raise HTTPException(400, {
            "key": "error.invalidBackup",
            "fallback": f"Invalid backup: {_safe_error_message(e)}",
        })
    except Exception as e:
        log_status("error", "backup", f"import_full failed: {e}")
        raise HTTPException(500, {
            "key": "error.importFailed",
            "fallback": f"Import failed: {_safe_error_message(e)}",
        })
    finally:
        try: os.remove(tmp_path)
        except OSError: pass


# ── Async full backup / import (Stage 3) ────────────────────────
from fastapi import Body
from fastapi.responses import StreamingResponse
import asyncio
import json as _json
import os as _os
from pydantic import BaseModel
from services.backup_jobs import (
    start_export_thread, start_import_thread,
    export_snapshot, import_snapshot,
    reset_import_state,
    EXPORT_EVENT, IMPORT_EVENT, cancel_import,
)


class ExportFullOptions(BaseModel):
    include_videos: bool = True
    include_versions: bool = True
    include_blur_regions: bool = True
    include_behavior_validations: bool = True
    include_streams: bool = False
    include_webhooks: bool = False


@router.post("/api/projects/{project_id}/export/full/async",
             dependencies=[Depends(require_permission("dataset.export"))])
def export_full_async(project_id: int,
                      payload: ExportFullOptions = Body(default_factory=ExportFullOptions),
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    try:
        from database import SessionLocal
        start_export_thread(
            SessionLocal, project_id,
            payload.model_dump(),
            requested_by=user.get("username"),
        )
    except RuntimeError as e:
        raise HTTPException(409, {"key": "error.exportAlreadyRunning",
                                  "fallback": str(e)})
    return {"status": "started",
            "poll_url": "/api/projects/export/full/status"}


@router.get("/api/projects/export/full/status")
def export_full_status(user: dict = Depends(get_current_user)):
    return export_snapshot()


@router.get("/api/projects/export/full/events")
async def export_full_events(user: dict = Depends(get_current_user)):
    async def gen():
        snap = export_snapshot()
        yield "data: " + _json.dumps(snap, ensure_ascii=False, default=str) + "\n\n"
        last = _json.dumps(snap, ensure_ascii=False, default=str)
        while True:
            await asyncio.get_event_loop().run_in_executor(
                None, EXPORT_EVENT.wait, 1.0)
            EXPORT_EVENT.clear()
            snap = export_snapshot()
            payload = _json.dumps(snap, ensure_ascii=False, default=str)
            if payload != last:
                yield "data: " + payload + "\n\n"
                last = payload
            if snap["status"] not in ("running", "stopping"):
                break
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/api/projects/export/full/download")
def export_full_download(user: dict = Depends(get_current_user)):
    snap = export_snapshot()
    if snap["status"] != "done" or not snap["zip_path"]:
        raise HTTPException(404, {"key": "error.backupNotReady",
                                  "fallback": "Backup not ready"})
    if not _os.path.exists(snap["zip_path"]):
        raise HTTPException(404, {"key": "error.backupFileMissing",
                                  "fallback": "Backup file missing"})
    return FileResponse(snap["zip_path"], media_type="application/zip",
                        filename=_os.path.basename(snap["zip_path"]))


@router.post("/api/projects/import/full/async",
             dependencies=[Depends(require_permission("project.manage"))])
def import_full_async(file: UploadFile = File(...),
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    _rate_limit(_limiter_import, "import_full",
                {"key": "error.rateLimitedImport",
                 "fallback": "Слишком много импортов."})
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, {"key": "error.invalidZip",
                                  "fallback": "Ожидается .zip"})

    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    total = 0
    try:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_IMPORT_BYTES:
                raise HTTPException(413, {
                    "key": "error.payloadTooLarge",
                    "fallback": "Archive too large"})
            tmp.write(chunk)
    finally:
        tmp.close()

    from database import SessionLocal
    try:
        start_import_thread(SessionLocal, tmp.name,
                            requested_by=user.get("username"))
    except RuntimeError as e:
        _os.remove(tmp.name)
        raise HTTPException(409, {"key": "error.importAlreadyRunning",
                                  "fallback": str(e)})
    return {"status": "started",
            "poll_url": "/api/projects/import/full/status"}


@router.get("/api/projects/import/full/status")
def import_full_status(user: dict = Depends(get_current_user)):
    return import_snapshot()


@router.get("/api/projects/import/full/events")
async def import_full_events(user: dict = Depends(get_current_user)):
    async def gen():
        snap = import_snapshot()
        yield "data: " + _json.dumps(snap, ensure_ascii=False, default=str) + "\n\n"
        last = _json.dumps(snap, ensure_ascii=False, default=str)
        while True:
            await asyncio.get_event_loop().run_in_executor(
                None, IMPORT_EVENT.wait, 1.0)
            IMPORT_EVENT.clear()
            snap = import_snapshot()
            payload = _json.dumps(snap, ensure_ascii=False, default=str)
            if payload != last:
                yield "data: " + payload + "\n\n"
                last = payload
            if snap["status"] not in ("running", "stopping"):
                break
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/api/projects/import/full/reset",
             dependencies=[Depends(require_permission("project.manage"))])
def import_full_reset(user: dict = Depends(get_current_user)):
    reset_import_state()
    return {"status": "ok"}


@router.post("/api/projects/import/full/cancel",
             dependencies=[Depends(require_permission("project.manage"))])
def import_full_cancel(user: dict = Depends(get_current_user)):
    cancel_import()
    return {"status": "cancelling"}
