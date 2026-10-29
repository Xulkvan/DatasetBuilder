"""[V13.2.0:pipeline-router] API endpoints для pipeline полной разметки."""
import asyncio
import json
from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from services.auth_service import get_current_user, require_permission
# [PATCH:RBAC_IMPORT]
from models import Project
from services.pipeline_service import (
    PIPELINE_LOCK, PIPELINE_EVENT, PIPELINE_STATE,
    _snapshot, start_pipeline, stop_pipeline,
)

router = APIRouter()


class PipelineStartIn:
    pass


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
                   db: Session = Depends(get_db)):
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
def pipeline_status(project_id: int):
    return _snapshot()


@router.post("/api/projects/{project_id}/pipeline/stop")
def pipeline_stop(project_id: int):
    stop_pipeline()
    return {"status": "stopping"}


@router.get("/api/projects/{project_id}/pipeline/events")
async def pipeline_events(project_id: int):
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
