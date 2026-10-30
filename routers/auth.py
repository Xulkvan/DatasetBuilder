"""[STAGE1:auth-router] Team Edition: /api/auth/* endpoints."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from database import get_db, DB_ENGINE
from models import User
from config import ROLE_ADMIN, ROLE_PERMISSIONS, resolve_auth_mode  # [STAGE6:permissions-matrix]
from services.auth_service import (
    hash_password, verify_password_and_upgrade,
    create_session, revoke_session, revoke_all_sessions,
    set_session_cookie, clear_session_cookie,
    set_csrf_cookie,  # [PATCH:STAGE2-CSRF-DOUBLE-SUBMIT]
    _needs_setup, get_current_user, SESSION_COOKIE_NAME,
)
from logger import log_status


router = APIRouter(tags=["auth"])

# [STAGE2:login-rate-limit]
from services.rate_limiter import SimpleRateLimiter, _rate_limit as _rl_check
_LOGIN_LIMITER_IP = SimpleRateLimiter(max_requests=20, window_sec=300)
_LOGIN_LIMITER_USER = SimpleRateLimiter(max_requests=5, window_sec=300)



class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    must_change_password: bool = False


class AuthStatusOut(BaseModel):
    mode: Literal["local", "team"]
    needs_setup: bool
    is_authenticated: bool
    user: Optional[UserOut] = None
    permissions: list[str] = Field(default_factory=list)  # [STAGE6:permissions-matrix]


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)


# [STAGE6:permissions-matrix] helpers
def _all_permissions() -> list:
    """Union всех permissions из config.ROLE_PERMISSIONS."""
    _all = set()
    for _perms in ROLE_PERMISSIONS.values():
        _all.update(_perms)
    return sorted(_all)


def _perms_for_user(user_dict) -> list:
    """Матрица прав для конкретного пользователя."""
    if not user_dict:
        return []
    if user_dict.get("local"):
        return _all_permissions()
    role = user_dict.get("role")
    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))


@router.get("/api/auth/status", response_model=AuthStatusOut)
def auth_status(request: Request):
    mode = resolve_auth_mode(DB_ENGINE)
    if mode == "local":
        return {
            "mode": "local",
            "needs_setup": False,
            "is_authenticated": True,
            "user": {"id": 0, "username": "local",
                     "role": ROLE_ADMIN, "must_change_password": False},
            "permissions": _all_permissions(),
        }
    user = getattr(request.state, "user", None)
    return {
        "mode": "team",
        "needs_setup": _needs_setup(),
        "is_authenticated": user is not None,
        "user": user,
        "permissions": _perms_for_user(user),
    }


@router.post("/api/auth/login")
def auth_login(payload: LoginIn, request: Request, response: Response,
               db: DBSession = Depends(get_db)):
    # [STAGE2:login-rate-limit] защита от brute-force
    _ip = request.client.host if request.client else "unknown"
    _rl_check(_LOGIN_LIMITER_IP, f"ip:{_ip}",
              {"key": "error.rateLimitedLogin", "fallback": "Слишком много попыток входа. Подождите."})
    _rl_check(_LOGIN_LIMITER_USER, f"user:{payload.username}",
              {"key": "error.rateLimitedLogin", "fallback": "Слишком много попыток входа. Подождите."})
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not user.is_active:
        raise HTTPException(
            401, {"key": "error.badCredentials",
                  "fallback": "Неверный логин или пароль"})
    if not verify_password_and_upgrade(payload.password, user, db):
        raise HTTPException(
            401, {"key": "error.badCredentials",
                  "fallback": "Неверный логин или пароль"})
    token = create_session(db, user, request)
    set_session_cookie(response, token, request)
    set_csrf_cookie(response, request)  # [PATCH:STAGE2-CSRF-DOUBLE-SUBMIT]
    log_status("info", "auth", f"login: {user.username}")
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "must_change_password": bool(getattr(user, "must_change_password", 0) or 0),
        },
        "permissions": sorted(ROLE_PERMISSIONS.get(user.role, frozenset())),
    }


@router.post("/api/auth/logout")
def auth_logout(request: Request, response: Response,
                db: DBSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    revoke_session(db, token)
    clear_session_cookie(response)
    response.delete_cookie("pdb_csrf", path="/")  # [PATCH:STAGE2-CSRF-DOUBLE-SUBMIT]
    return {"status": "ok"}


@router.get("/api/auth/me")
def auth_me(user: dict = Depends(get_current_user)):
    # [STAGE6:permissions-matrix] отдаём permissions вместе с профилем
    return {**user, "permissions": _perms_for_user(user)}


@router.get("/api/permissions")
def get_permissions(user: dict = Depends(get_current_user)):
    """[STAGE6:permissions-matrix] Матрица прав текущего пользователя."""
    return {
        "role": user.get("role"),
        "permissions": _perms_for_user(user),
        "local": bool(user.get("local")),
    }


@router.post("/api/auth/change_password")
def auth_change_password(payload: ChangePasswordIn, request: Request,
                         response: Response,
                         db: DBSession = Depends(get_db),
                         user: dict = Depends(get_current_user)):
    if user.get("local"):
        raise HTTPException(400, "Cannot change password in local mode")
    db_user = db.query(User).filter(User.id == user["id"]).first()
    if not db_user:
        raise HTTPException(404, {"key": "error.userNotFound",
                                  "fallback": "Пользователь не найден"})
    if not verify_password_and_upgrade(payload.old_password, db_user, db):
        raise HTTPException(401, {"key": "error.badCredentials",
                                  "fallback": "Неверный пароль"})
    db_user.password_hash = hash_password(payload.new_password)
    try:
        db_user.must_change_password = 0
    except Exception:
        pass
    db.commit()
    revoke_all_sessions(db, db_user.id)
    token = create_session(db, db_user, request)
    set_session_cookie(response, token, request)
    log_status("info", "auth", f"password changed: {db_user.username}")
    return {"status": "ok"}
