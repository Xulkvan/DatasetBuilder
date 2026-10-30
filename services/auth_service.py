"""[STAGE1:auth-service] Team Edition: auth core.

Provides:
  - password hashing (argon2, with SHA256 auto-upgrade)
  - session CRUD (opaque tokens in DB)
  - auth_middleware_fn(request, call_next)
  - get_current_user(request)            — FastAPI dependency
  - require_permission(perm)             — FastAPI dependency factory

CLI:
  python -m services.auth_service reset-password <new_password>
"""
import hashlib
import secrets
import sys
import time
from datetime import timedelta
from typing import Optional

from fastapi import HTTPException, Request, Response, Depends
from fastapi.responses import JSONResponse

from database import SessionLocal, DB_ENGINE
from models import Session as SessionModel, User
from config import (
    SESSION_COOKIE_NAME, SESSION_TTL_DAYS,
    SESSION_COOKIE_SECURE, SESSION_COOKIE_SAMESITE,
    SESSION_REFRESH_INTERVAL, ROLE_PERMISSIONS, ROLE_ADMIN,
    resolve_auth_mode,
)
from logger import log_status, utcnow


# ---------- Password hashing ----------
try:
    from argon2 import PasswordHasher
    _PH = PasswordHasher()
    _HAS_ARGON = True
except ImportError:
    _PH = None
    _HAS_ARGON = False


def hash_password(plain: str) -> str:
    # [PATCH:REVERT_ARGON2_FALLBACK]
    if not _HAS_ARGON:
        raise RuntimeError(
            "argon2-cffi is not installed. Install it: pip install argon2-cffi"
        )
    return _PH.hash(plain)
    # [/PATCH:REVERT_ARGON2_FALLBACK]


def verify_password_and_upgrade(plain: str, user, db) -> bool:
    """Verify password; upgrade legacy SHA256 hash to argon2 on success."""
    stored = getattr(user, "password_hash", "") or ""
    if stored.startswith("$argon2"):
        if not _HAS_ARGON:
            return False
        try:
            return bool(_PH.verify(stored, plain))
        except Exception:
            return False
    if len(stored) == 64:  # legacy SHA256 (hex)
        if hashlib.sha256(plain.encode("utf-8")).hexdigest() == stored:
            if _HAS_ARGON:
                try:
                    user.password_hash = _PH.hash(plain)
                    db.commit()
                    log_status("info", "auth",
                               f"legacy sha256 upgraded for user id={user.id}")
                except Exception:
                    pass
            else:  # [PATCH:STAGE2-ARGON2-FALLBACK-WARN]
                log.warning("argon2-cffi not installed; SHA256 password for user id=%s "
                            "cannot be upgraded to argon2", user.id)
            return True
    return False


# ---------- Sessions ----------
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db, user, request: Optional[Request]) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    ua = ""
    ip = None
    if request is not None:
        ua = (request.headers.get("user-agent") or "")[:256]
        if request.client:
            ip = request.client.host
    db.add(SessionModel(
        token_hash=_token_hash(token),
        user_id=user.id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=SESSION_TTL_DAYS),
        user_agent=ua or None,
        ip_at_login=ip,
    ))
    db.commit()
    return token


def resolve_session(db, token: str) -> Optional[dict]:
    if not token:
        return None
    now = utcnow()
    row = (
        db.query(SessionModel, User)
          .join(User, User.id == SessionModel.user_id)
          .filter(
              SessionModel.token_hash == _token_hash(token),
              SessionModel.expires_at > now,
              User.is_active == 1,
          )
          .first()
    )
    if not row:
        return None
    sess, user = row
    if (now - sess.last_seen_at).total_seconds() > SESSION_REFRESH_INTERVAL:
        sess.last_seen_at = now
        db.commit()
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "must_change_password": bool(getattr(user, "must_change_password", 0) or 0),
    }


def revoke_session(db, token: str) -> None:
    if not token:
        return
    db.query(SessionModel).filter(SessionModel.token_hash == _token_hash(token)).delete()
    db.commit()


def revoke_all_sessions(db, user_id: int) -> None:
    db.query(SessionModel).filter(SessionModel.user_id == user_id).delete()
    db.commit()


def set_session_cookie(response: Response, token: str,
                       request: Optional[Request]) -> None:
    s = str(SESSION_COOKIE_SECURE).lower()
    if s == "auto":
        use_secure = bool(request and request.url.scheme == "https")
    else:
        use_secure = s in ("1", "true", "yes")
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_DAYS * 86400,
        httponly=True,
        secure=use_secure,
        samesite=SESSION_COOKIE_SAMESITE,
        path="/",
    )
    # [PATCH:STAGE2-COOKIE-SECURE-WARN]
    try:
        if not use_secure and resolve_auth_mode(DB_ENGINE) == "team":
            log.warning("Session cookie без Secure-флага в team mode. "
                        "Используйте HTTPS в проде.")
    except Exception:
        pass


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def set_csrf_cookie(response: Response, request: Optional[Request]) -> str:  # [PATCH:STAGE2-CSRF-DOUBLE-SUBMIT]
    """Double-submit CSRF cookie. НЕ HttpOnly — JS должен читать."""
    import secrets as _secrets
    csrf_token = _secrets.token_urlsafe(32)
    s = str(SESSION_COOKIE_SECURE).lower()
    if s == "auto":
        use_secure = bool(request and request.url.scheme == "https")
    else:
        use_secure = s in ("1", "true", "yes")
    response.set_cookie(
        key="pdb_csrf",
        value=csrf_token,
        max_age=SESSION_TTL_DAYS * 86400,
        httponly=False,
        secure=use_secure,
        samesite=SESSION_COOKIE_SAMESITE,
        path="/",
    )
    return csrf_token


# ---------- Setup state (cache to avoid DB hit on every request) ----------
_setup_cache = {"value": None, "at": 0.0}
_SETUP_CACHE_TTL = 5.0


def _needs_setup() -> bool:
    now = time.time()
    if _setup_cache["value"] is not None and now - _setup_cache["at"] < _SETUP_CACHE_TTL:
        return _setup_cache["value"]
    db = SessionLocal()
    try:
        n = db.query(User).count()
    finally:
        db.close()
    _setup_cache["value"] = (n == 0)
    _setup_cache["at"] = now
    return _setup_cache["value"]


def invalidate_setup_cache() -> None:
    _setup_cache["value"] = None
    _setup_cache["at"] = 0.0


# ---------- Middleware ----------
# [PATCH:STAGE4_AUTH_MIDDLEWARE_REMOVED] auth_middleware_fn/
# permission_middleware_fn/_PUBLIC_*/_is_public удалены
# (не регистрировались в app.py — app.py использует
# _global_auth_middleware + _v2_api_key_guard).
# ---------- Dependencies ----------
def get_current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            401,
            {"key": "error.unauthorized", "fallback": "Требуется авторизация"},
        )
    return user


def require_permission(perm: str):
    def _checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("local"):
            return user
        role = user.get("role")
        if perm not in ROLE_PERMISSIONS.get(role, frozenset()):
            raise HTTPException(
                403,
                {"key": "error.forbidden", "fallback": "Недостаточно прав"},
            )
        return user
    return _checker


# ---------- CLI ----------
def _cli() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "reset-password":
        new_pw = sys.argv[2]
        uname = input("username: ").strip()
        if not uname or len(new_pw) < 8:
            print("Usage: python -m services.auth_service reset-password <new_password>")
            print("       (password >= 8 chars, username asked interactively)")
            return 2
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            if not u:
                print(f"User '{uname}' not found")
                return 1
            u.password_hash = hash_password(new_pw)
            try:
                u.must_change_password = 0
            except Exception:
                pass
            db.commit()
            print(f"Password reset for '{uname}'")
            return 0
        finally:
            db.close()
    print("Usage: python -m services.auth_service reset-password <new_password>")
    return 2


if __name__ == "__main__":
    sys.exit(_cli())


# [PATCH:STAGE4_AUTH_PERM_MW_REMOVED]
# permission_middleware_fn удалён — RBAC выполняется в
# app.py::_global_auth_middleware через match_permission().
# [/PATCH:STAGE4_AUTH_PERM_MW_REMOVED]

