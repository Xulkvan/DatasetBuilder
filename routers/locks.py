"""[STAGE5:locks-router] Soft image locking (advisory, TTL-based).

Endpoints:
  POST   /api/images/{id}/lock            вЂ” try to acquire
  POST   /api/images/{id}/lock/heartbeat  вЂ” extend
  DELETE /api/images/{id}/lock            вЂ” release
  GET    /api/images/{id}/lock            вЂ” check current holder

Behavior:
  * acquire вЂ” upsert image_locks row if free/expired/owned-by-same-user.
  * on acquire failure вЂ” returns {status:'busy', holder:{username, acquired_at}}.
  * TTL = LOCK_TTL_SECONDS from config (default 300).
  * cron-free: expired locks are ignored on read.
"""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession

from database import get_db
from models import ImageModel, ImageLock, User
from services.auth_service import get_current_user, require_permission
from config import LOCK_TTL_SECONDS, SESSION_COOKIE_NAME
from services.auth_service import _token_hash  # noqa: F401
from services.project_access import check_image_access
from logger import utcnow


router = APIRouter(tags=["locks"])


def _cleanup_expired(db):
    now = utcnow()
    db.query(ImageLock).filter(ImageLock.expires_at <= now).delete(
        synchronize_session=False)


def _get_image_or_404(db, image_id: int, user: dict) -> ImageModel:
    img = check_image_access(db, image_id, user)
    if img.is_deleted:
        raise HTTPException(404, {"key": "error.imageNotFound",
                                  "fallback": "Image not found"})
    return img


def _get_session_id(db, request: Request) -> int:
    """Best-effort: current session id from cookie. Returns 0 if unknown."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return 0
    from models import Session as SessModel
    th = _token_hash(token)
    row = db.query(SessModel.id).filter(SessModel.token_hash == th).first()
    return int(row.id) if row else 0


@router.get("/api/images/{image_id}/lock")
def get_lock(image_id: int, db: DBSession = Depends(get_db),
             user: dict = Depends(require_permission("annotation.write"))):
    _cleanup_expired(db)
    db.commit()  # СЃРѕС…СЂР°РЅРёС‚СЊ РѕС‡РёСЃС‚РєСѓ РёСЃС‚С‘РєС€РёС… Р»РѕРєРѕРІ
    img = _get_image_or_404(db, image_id, user)
    lock = db.query(ImageLock).filter(ImageLock.image_id == image_id).first()
    if not lock:
        return {"status": "free", "image_id": image_id}
    holder = db.query(User).filter(User.id == lock.user_id).first()
    return {
        "status": "locked",
        "image_id": image_id,
        "holder": {
            "id": lock.user_id,
            "username": holder.username if holder else "?",
            "acquired_at": lock.acquired_at.isoformat() if lock.acquired_at else None,
        },
        "expires_at": lock.expires_at.isoformat() if lock.expires_at else None,
        "is_mine": bool(user and not user.get("local") and lock.user_id == user.get("id")),
    }


@router.post("/api/images/{image_id}/lock")
def acquire_lock(image_id: int, request: Request,
                 db: DBSession = Depends(get_db),
                 user: dict = Depends(require_permission("annotation.write"))):
    if user.get("local"):
        return {"status": "acquired", "image_id": image_id, "expires_at": (utcnow() + timedelta(seconds=LOCK_TTL_SECONDS)).isoformat()}
    _cleanup_expired(db)
    img = _get_image_or_404(db, image_id, user)
    now = utcnow()
    expires = now + timedelta(seconds=LOCK_TTL_SECONDS)

    uid = 0 if user.get("local") else int(user.get("id") or 0)
    sid = _get_session_id(db, request) or 0

    lock = db.query(ImageLock).filter(ImageLock.image_id == image_id).first()
    if lock is None:
        db.add(ImageLock(
            image_id=image_id, user_id=uid, session_id=sid or None,
            acquired_at=now, expires_at=expires,
        ))
        db.commit()
        return {"status": "acquired", "image_id": image_id,
                "expires_at": expires.isoformat()}

    # user.get("local") handled by early-return above
    if lock.user_id == uid:
        lock.expires_at = expires
        lock.acquired_at = now
        if sid:
            lock.session_id = sid
        db.commit()
        return {"status": "acquired", "image_id": image_id,
                "expires_at": expires.isoformat()}

    holder = db.query(User).filter(User.id == lock.user_id).first()
    return {
        "status": "busy",
        "image_id": image_id,
        "holder": {
            "id": lock.user_id,
            "username": holder.username if holder else "?",
            "acquired_at": lock.acquired_at.isoformat() if lock.acquired_at else None,
        },
        "expires_at": lock.expires_at.isoformat() if lock.expires_at else None,
    }


@router.post("/api/images/{image_id}/lock/heartbeat")
def heartbeat_lock(image_id: int, db: DBSession = Depends(get_db),
                   user: dict = Depends(require_permission("annotation.write"))):
    _get_image_or_404(db, image_id, user)
    _cleanup_expired(db)
    uid = 0 if user.get("local") else int(user.get("id") or 0)
    lock = db.query(ImageLock).filter(ImageLock.image_id == image_id).first()
    if not lock:
        return {"status": "not_locked", "image_id": image_id}
    if lock.user_id != uid and not user.get("local"):
        return {"status": "not_mine", "image_id": image_id}
    now = utcnow()
    lock.expires_at = now + timedelta(seconds=LOCK_TTL_SECONDS)
    db.commit()
    return {"status": "ok", "expires_at": lock.expires_at.isoformat()}


@router.delete("/api/images/{image_id}/lock")
def release_lock(image_id: int, db: DBSession = Depends(get_db),
                 user: dict = Depends(require_permission("annotation.write"))):
    _get_image_or_404(db, image_id, user)
    uid = 0 if user.get("local") else int(user.get("id") or 0)
    lock = db.query(ImageLock).filter(ImageLock.image_id == image_id).first()
    if not lock:
        return {"status": "not_locked", "image_id": image_id}
    if lock.user_id != uid and not user.get("local"):
        raise HTTPException(403, {"key": "error.notYourLock",
                                  "fallback": "Lock belongs to another user"})
    db.delete(lock)
    db.commit()
    return {"status": "released", "image_id": image_id}
