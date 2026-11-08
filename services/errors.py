"""services/errors.py — [PATCH:STAGE6-F15-C18] shared error utils.

Единая точка правды для _safe_error_message и _db_commit_safe.
Импортируется из app.py, services/track_service.py и др.
"""
import logging
import re

log = logging.getLogger("db")


def _safe_error_message(e: Exception, context: str = "") -> str:
    name = type(e).__name__
    if ("OperationalError" in name or "IntegrityError" in name
            or "ProgrammingError" in name):
        return f"{context}: ошибка БД" if context else "Ошибка БД"
    msg = re.sub(r'/[^\s]+/', '/…/', str(e))[:200]
    return f"{context}: {msg}" if context else msg


def _db_commit_safe(db):
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning("DB commit failed: %s", e)
        raise


def api_error(status: int, key: str, fallback: str, **params):
    """Stage 5.9 — единый формат ошибок API: {"key","fallback","params"}."""
    from fastapi import HTTPException
    detail: dict = {"key": key, "fallback": fallback}
    if params:
        detail["params"] = params
    return HTTPException(status_code=status, detail=detail)
