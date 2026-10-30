"""[STAGE4:assignments-router] Task assignment + review workflow.

Endpoints:
  POST /api/projects/{id}/assign                  — assign image_ids to user_id
  POST /api/projects/{id}/assign/round_robin      — round-robin split
  POST /api/images/{id}/submit_for_review         — annotator marks as done
  POST /api/images/{id}/approve                   — reviewer approves
  POST /api/images/{id}/reject                    — reviewer rejects (+comment)
  GET  /api/projects/{id}/my_tasks                — my assigned images
  GET  /api/projects/{id}/review_queue            — pending review images
  GET  /api/projects/{id}/assignment_stats        — per-user progress

Permission model:
  assign*            — project.manage  (Manager/Admin)
  submit_for_review  — annotation.write (any annotator)
  approve/reject     — annotation.review (Manager/Admin/Reviewer)
  my_tasks           — annotation.write
  review_queue       — annotation.review
  assignment_stats   — project.manage
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session as DBSession

from collections import defaultdict  # [PATCH:STAGE4_ASSIGN_DEFAULTDICT_IMPORT]

from database import get_db
from models import ImageModel, Project, User
from services.auth_service import get_current_user, require_permission # [PATCH:STAGE3_ASSIGN]
from logger import utcnow, log_status


router = APIRouter(tags=["assignments"])


VALID_REVIEW_STATUSES = (
    "unassigned", "assigned", "in_progress", "review", "approved", "rejected",
)


class AssignIn(BaseModel):
    image_ids: list[int] = Field(..., min_length=1)
    user_id: int
    review_status: str = "assigned"


class RoundRobinIn(BaseModel):
    image_ids: list[int] = Field(..., min_length=1)
    user_ids: list[int] = Field(..., min_length=1)


class ReviewIn(BaseModel):
    comment: Optional[str] = None


def _get_project_or_404(db, project_id: int) -> Project:
    proj = db.query(Project).filter(
        Project.id == project_id, Project.is_deleted.is_(False)).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                  "fallback": "Project not found"})
    return proj


def _verify_user_exists(db, user_id: int) -> User:
    u = db.query(User).filter(User.id == user_id, User.is_active == 1).first()
    if not u:
        raise HTTPException(404, {"key": "error.userNotFound",
                                  "fallback": "User not found"})
    return u


@router.post("/api/projects/{project_id}/assign")
def assign_images(project_id: int, payload: AssignIn,
                  request: Request, db: DBSession = Depends(get_db),
                  user: dict = Depends(require_permission("project.manage"))):
    _get_project_or_404(db, project_id)
    _verify_user_exists(db, payload.user_id)
    if payload.review_status not in VALID_REVIEW_STATUSES:
        raise HTTPException(400, f"invalid review_status: {payload.review_status}")
    imgs = db.query(ImageModel).filter(
        ImageModel.id.in_(payload.image_ids),
        ImageModel.project_id == project_id,
        ImageModel.is_deleted.is_(False),
    ).all()
    if not imgs:
        raise HTTPException(404, {"key": "error.imagesNotFound",
                                  "fallback": "No images found"})
    now = utcnow()
    for im in imgs:
        im.assigned_to = payload.user_id
        im.assigned_at = now
        im.review_status = payload.review_status
    db.commit()
    log_status("info", "project",
               f"assign: {len(imgs)} images -> user_id={payload.user_id} "
               f"by {user.get('username')}")
    return {"assigned": len(imgs), "user_id": payload.user_id,
            "review_status": payload.review_status}


@router.post("/api/projects/{project_id}/assign/round_robin")
def assign_round_robin(project_id: int, payload: RoundRobinIn,
                       request: Request, db: DBSession = Depends(get_db),
                       user: dict = Depends(require_permission("project.manage"))):
    _get_project_or_404(db, project_id)
    for uid in payload.user_ids:
        _verify_user_exists(db, uid)
    imgs = (db.query(ImageModel)
              .filter(ImageModel.id.in_(payload.image_ids),
                      ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False))
              .order_by(ImageModel.id).all())
    if not imgs:
        raise HTTPException(404, {"key": "error.imagesNotFound",
                                  "fallback": "No images found"})
    n = len(payload.user_ids)
    now = utcnow()
    counts = {uid: 0 for uid in payload.user_ids}
    for i, im in enumerate(imgs):
        uid = payload.user_ids[i % n]
        im.assigned_to = uid
        im.assigned_at = now
        im.review_status = "assigned"
        counts[uid] += 1
    db.commit()
    log_status("info", "project",
               f"round_robin: {len(imgs)} images -> {counts} "
               f"by {user.get('username')}")
    return {"assigned": len(imgs), "per_user": counts}


@router.post("/api/images/{image_id}/submit_for_review")
def submit_for_review(image_id: int, request: Request,
                      db: DBSession = Depends(get_db),
                      user: dict = Depends(require_permission("annotation.write"))):
    img = db.query(ImageModel).filter(
        ImageModel.id == image_id, ImageModel.is_deleted.is_(False)).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound",
                                  "fallback": "Image not found"})
    if user.get("local"):
        pass
    else:
        if img.assigned_to is not None and img.assigned_to != user["id"]:
            raise HTTPException(403, {"key": "error.notYourTask",
                                      "fallback": "Not assigned to you"})
    if img.review_status not in ("assigned", "in_progress", "rejected", "unassigned"):
        raise HTTPException(400, {"key": "error.badReviewState",
                                  "fallback":
                                  f"Cannot submit from '{img.review_status}'"})
    img.review_status = "review"
    db.commit()
    log_status("info", "project",
               f"submit_for_review: image #{image_id} by {user.get('username')}")
    return {"status": "review", "image_id": image_id}


@router.post("/api/images/{image_id}/approve")
def approve_image(image_id: int, payload: Optional[ReviewIn] = None,
                  request: Request = None,
                  db: DBSession = Depends(get_db),
                  user: dict = Depends(require_permission("annotation.review"))):
    img = db.query(ImageModel).filter(
        ImageModel.id == image_id, ImageModel.is_deleted.is_(False)).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound",
                                  "fallback": "Image not found"})
    if img.review_status != "review":
        raise HTTPException(400, {"key": "error.badReviewState",
                                  "fallback":
                                  f"Cannot approve from '{img.review_status}'"})
    img.review_status = "approved"
    img.reviewed_at = utcnow()
    try:
        img.reviewed_by = user.get("id") or None
    except Exception:
        pass
    img.review_comment = (payload.comment if payload else None) or None
    db.commit()
    log_status("success", "project",
               f"approved: image #{image_id} by {user.get('username')}")
    return {"status": "approved", "image_id": image_id}


@router.post("/api/images/{image_id}/reject")
def reject_image(image_id: int, payload: Optional[ReviewIn] = None,
                 request: Request = None,
                 db: DBSession = Depends(get_db),
                 user: dict = Depends(require_permission("annotation.review"))):
    img = db.query(ImageModel).filter(
        ImageModel.id == image_id, ImageModel.is_deleted.is_(False)).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound",
                                  "fallback": "Image not found"})
    if img.review_status != "review":
        raise HTTPException(400, {"key": "error.badReviewState",
                                  "fallback":
                                  f"Cannot reject from '{img.review_status}'"})
    img.review_status = "rejected"
    img.reviewed_at = utcnow()
    try:
        img.reviewed_by = user.get("id") or None
    except Exception:
        pass
    img.review_comment = (payload.comment if payload else None) or None
    db.commit()
    log_status("warning", "project",
               f"rejected: image #{image_id} by {user.get('username')}")
    return {"status": "rejected", "image_id": image_id}


@router.get("/api/projects/{project_id}/my_tasks")
def my_tasks(project_id: int, request: Request,
             status: Optional[str] = None,
             limit: int = 200,
             db: DBSession = Depends(get_db),
             user: dict = Depends(require_permission("annotation.write"))):
    _get_project_or_404(db, project_id)
    if user.get("local"):
        uid = None
    else:
        uid = user["id"]
    q = db.query(ImageModel.id).filter(
        ImageModel.project_id == project_id,
        ImageModel.is_deleted.is_(False),
    )
    if uid is not None:
        q = q.filter(ImageModel.assigned_to == uid)
    if status:
        if status not in VALID_REVIEW_STATUSES:
            raise HTTPException(400, f"invalid status: {status}")
        q = q.filter(ImageModel.review_status == status)
    rows = q.order_by(ImageModel.id).limit(min(limit, 1000)).all()
    return {"items": [int(r.id) for r in rows], "total": len(rows)}


@router.get("/api/projects/{project_id}/review_queue")
def review_queue(project_id: int, limit: int = 200,
                 db: DBSession = Depends(get_db),
                 user: dict = Depends(require_permission("annotation.review"))):
    _get_project_or_404(db, project_id)
    rows = (db.query(ImageModel.id)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False),
                      ImageModel.review_status == "review")
              .order_by(ImageModel.id).limit(min(limit, 1000)).all())
    return {"items": [int(r.id) for r in rows], "total": len(rows)}


@router.get("/api/projects/{project_id}/assignment_stats")
def assignment_stats(project_id: int, db: DBSession = Depends(get_db),
                     user: dict = Depends(require_permission("project.manage"))):
    _get_project_or_404(db, project_id)
    rows = (db.query(ImageModel.assigned_to, ImageModel.review_status,
                     func.count(ImageModel.id))
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False))
              .group_by(ImageModel.assigned_to, ImageModel.review_status)
              .all())
    users = {u.id: u.username for u in db.query(User).all()}
    out = defaultdict(lambda: defaultdict(int))
    for uid, status, cnt in rows:
        key = users.get(uid) if uid else "_unassigned"
        out[key][status] = int(cnt)
    return {"stats": {k: dict(v) for k, v in out.items()}}
# [PATCH:STAGE4_ASSIGN_DEFAULTDICT_BOTTOM]


# [/STAGE4:assignments-router]
