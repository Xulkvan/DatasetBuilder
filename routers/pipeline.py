"""[V13.2.0:pipeline-router] API endpoints для pipeline полной разметки."""
import asyncio
import json
from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from services.auth_service import get_current_user, require_permission
# [STAGE-SEC1:imports]
from services.project_access import check_project_access

# [PATCH:RBAC_IMPORT]
from models import Project
from services.pipeline_service import (
    PIPELINE_LOCK, PIPELINE_EVENT, PIPELINE_STATE,
    _snapshot, start_pipeline, stop_pipeline,
)

router = APIRouter()


# [PATCH:STAGE4_PIPELINE_DEAD_REMOVED] PipelineStartIn удалён (не использовался).

def _parse_payload(payload):
    if not isinstance(payload, dict):
        payload = {}
    mode = payload.get("mode") or "add"
    stages = payload.get("stages") or None
    if stages is not None and not isinstance(stages, dict):
        stages = None
    return mode, stages


@router.post("/api/projects/{project_id}/pipeline/start", dependencies=[Depends(require_permission("pipeline.run"))])
def pipeline_start(project_id: int, payload: dict = Body(default_factory=dict),
                   user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    # [STAGE-SEC1]:check:pipeline_start
    check_project_access(db, project_id, user)
    proj = db.query(Project).filter(Project.id == project_id,
                                    Project.is_deleted.is_(False)).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    mode, stages = _parse_payload(payload)
    try:
        start_pipeline(project_id, mode=mode, enabled_stages=stages)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"status": "started", "mode": mode}


@router.get("/api/projects/{project_id}/pipeline/status")
def pipeline_status(project_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    # [STAGE-SEC1]:check:pipeline_status
    check_project_access(db, project_id, user)
    return _snapshot()


@router.post("/api/projects/{project_id}/pipeline/stop")
def pipeline_stop(project_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    # [STAGE-SEC1]:check:pipeline_stop
    check_project_access(db, project_id, user)
    stop_pipeline()
    return {"status": "stopping"}


@router.get("/api/projects/{project_id}/pipeline/events")
async def pipeline_events(project_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    # [STAGE-SEC1]:check:pipeline_events
    check_project_access(db, project_id, user)
    async def gen():
        snap = _snapshot()
        payload = json.dumps(snap, ensure_ascii=False, default=str)
        yield "data: " + payload + "\n\n"
        last = payload
        while True:
            await asyncio.get_event_loop().run_in_executor(None, PIPELINE_EVENT.wait, 1.0)
            PIPELINE_EVENT.clear()
            snap = _snapshot()
            payload = json.dumps(snap, ensure_ascii=False, default=str)
            if payload != last:
                yield "data: " + payload + "\n\n"
                last = payload
            if snap["status"] not in ("running", "stopping"):
                break
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ============================================================================
# [PATCH:STAGE2-F-11-rollback] Rollback проекта из pre_replace_backup.
# ============================================================================
@router.post("/api/projects/{project_id}/pipeline/rollback",
             dependencies=[Depends(require_permission("pipeline.run"))])
def pipeline_rollback(project_id: int,
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Восстанавливает проект из pre_replace_backup (после ошибки pipeline)."""
    import os as _os
    from logger import log_status as _ls
    check_project_access(db, project_id, user)
    with PIPELINE_LOCK:
        _bp_raw = PIPELINE_STATE.get("pre_replace_backup")
    # [FIX:STAGE2-mypy-pipeline] PIPELINE_STATE — обычный dict, get()
    # возвращает union. Явно сужаем до str | None, чтобы mypy видел
    # os.path.exists(str) и restore_backup(..., str).
    bp: str | None = _bp_raw if isinstance(_bp_raw, str) else None
    if not bp or not _os.path.exists(bp):
        raise HTTPException(404, {"key": "error.backupNotFound",
                                 "fallback":
                                 "Pre-replace backup не найден "
                                 "(pipeline не запускался в replace-режиме "
                                 "или бэкап уже удалён)"})
    from services.backup_service import restore_backup
    try:
        r = restore_backup(db, project_id, bp)
    except Exception as e:
        _ls("error", "pipeline", f"Rollback failed: {e}")
        raise HTTPException(500, f"Rollback failed: {e}")
    _ls("warning", "pipeline",
        f"Rollback проекта #{project_id} из {_os.path.basename(bp)}")
    return {"status": "ok", **r, "backup": _os.path.basename(bp)}
