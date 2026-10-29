"""[STAGE1:setup-router] First-run setup wizard."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from database import get_db, DB_ENGINE
from models import User
from config import ROLE_ADMIN, resolve_auth_mode
from services.auth_service import (
    hash_password, create_session, set_session_cookie,
    _needs_setup, invalidate_setup_cache,
)
from logger import log_status, utcnow


router = APIRouter(tags=["setup"])


class SetupAdminIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


@router.get("/api/setup/status")
def setup_status():
    return {
        "needs_setup": _needs_setup(),
        "mode": resolve_auth_mode(DB_ENGINE),
    }


@router.post("/api/setup/admin")
def setup_admin(payload: SetupAdminIn, request: Request, response: Response,
                db: DBSession = Depends(get_db)):
    if resolve_auth_mode(DB_ENGINE) != "team":
        raise HTTPException(400, {"key": "error.setupLocalMode",
                                  "fallback": "Setup недоступен в local mode"})
    if not _needs_setup():
        raise HTTPException(409, {"key": "error.setupAlreadyDone",
                                  "fallback": "Настройка уже выполнена"})
    username = payload.username.strip()
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, {"key": "error.usernameTaken",
                                  "fallback": "Это имя уже занято"})
    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        role=ROLE_ADMIN,
        is_active=1,
        created_at=utcnow(),
    )
    try:
        user.must_change_password = 0
    except Exception:
        pass
    db.add(user)
    db.commit()
    db.refresh(user)
    invalidate_setup_cache()
    token = create_session(db, user, request)
    set_session_cookie(response, token, request)
    log_status("success", "system",
               f"Создан первый администратор: {user.username}")
    return {"user": {"id": user.id, "username": user.username, "role": user.role}}
