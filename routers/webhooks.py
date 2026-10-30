"""[STAGE3:webhooks-router] CRUD для Webhook."""
from __future__ import annotations

import uuid

from typing import Literal  # [PATCH:STAGE4_WEBHOOKS_LITERAL_IMPORT]

from fastapi import APIRouter, Depends, HTTPException, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Project, Webhook
from logger import utcnow, log_status

router = APIRouter()


class WebhookIn(BaseModel):
    url: str
    event_type: Literal[
        "annotation.saved",
        "training.completed",
        "dataset.exported",
    ] = "annotation.saved"  # [PATCH:STAGE4_WEBHOOKS_LITERAL_CLASS]
    secret_key: str = ""


@router.get("/api/projects/{project_id}/webhooks")
def list_webhooks(project_id: int, db: Session = Depends(get_db)):
    rows = (db.query(Webhook)
              .filter(Webhook.project_id == project_id)
              .order_by(Webhook.id.desc()).all())
    return [{
        "id": r.id,
        "url": r.url,
        "event_type": r.event_type,
        "active": bool(r.active),
        "has_secret": bool(r.secret_key),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@router.post("/api/projects/{project_id}/webhooks")
def create_webhook(project_id: int, payload: WebhookIn,
                   db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    if not payload.url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL должен начинаться с http:// или https://")
    wh = Webhook(project_id=project_id,
                 url=payload.url,
                 event_type=payload.event_type or "annotation.saved",
                 secret_key=payload.secret_key or "",
                 active=True,
                 created_at=utcnow())
    db.add(wh); db.commit(); db.refresh(wh)
    log_status("success", "settings",
               f"Webhook создан: {wh.event_type} -> {wh.url}")
    return {"id": wh.id, "url": wh.url,
            "event_type": wh.event_type, "active": True}


@router.delete("/api/webhooks/{webhook_id}")
def delete_webhook(webhook_id: int, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(404, "Webhook not found")
    db.delete(wh); db.commit()
    return {"status": "ok"}


@router.post("/api/webhooks/{webhook_id}/toggle")
def toggle_webhook(webhook_id: int, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(404, "Webhook not found")
    wh.active = not bool(wh.active)
    db.commit()
    return {"id": wh.id, "active": bool(wh.active)}


@router.post("/api/webhooks/{webhook_id}/test")
def test_webhook(webhook_id: int, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(404, "Webhook not found")
    from services.webhook_service import _sign, _post_once
    import json
    body = json.dumps({"event": "test", "webhook_id": wh.id,
                       "message": "DatasetBuilder webhook test"}).encode("utf-8")
    ok = _post_once(wh.url, body, _sign(body, wh.secret_key or ""))
    return {"ok": ok, "url": wh.url}
