"""V8.1.0: security middleware — CSRF, CSP, X-Frame, nosniff.

Все write-запросы (POST/PATCH/DELETE/PUT) требуют заголовок
`X-Requested-With: DatasetBuilder`, который не выставляется обычными
HTML-формами. Это блокирует классический CSRF на localhost.

CSP настроен максимально строго, но так, чтобы не сломать inline-скрипты
index.html (theme init, i18n fallback) — для них оставлен 'unsafe-inline'.
"""
import os
import secrets
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "DatasetBuilder"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# NOTE: style-src 'unsafe-inline'
# оставлен осознанно: inline style="..." в HTML (nonce не работает
# для атрибутов). Для self-hosted это приемлемый компромисс.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    # Разделяем style-src и
    # style-src-attr: теги <style> запрещены (главный вектор XSS
    # через style-инъекции), inline-атрибуты style="..." разрешены.
    "style-src 'self'; "
    "style-src-attr 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self';"
)


# [FIX-STAGE:AUDIT-V2]
def _write_audit_log(request: Request, status_code: int = 0,
                     duration_ms: float = 0.0) -> None:
    """Пишет запись в AuditLog для POST/PUT/DELETE (fire-and-forget)."""
    try:
        from database import SessionLocal
        from models import AuditLog
        from logger import utcnow
        # единый proxy-aware резолвер IP
        from services.client_ip import get_client_ip
        ip = get_client_ip(request)
        details = "%s %s [%s] %.0fms" % (
            request.method, request.url.path[:400],
            status_code, duration_ms,
        )
        db = SessionLocal()
        try:
            db.add(AuditLog(
                timestamp=utcnow(),
                user_ip=ip or None,
                
                user_id=(getattr(request.state, "user", None) or {}).get("id"),

                username=(getattr(request.state, "user", None) or {}).get("username"),action=request.method,
                details=details[:500],
            ))
            db.commit()
        finally:
            db.close()
    except Exception as _e:
        # debug-уровень, не шумит в проде
        import logging as _lg
        _lg.getLogger("db").debug("audit write failed: %s", _e)


async def _audit_async(request: Request, status_code: int,
                       duration_ms: float) -> None:
    """Обёртка для asyncio.create_task — не блокирует event loop."""
    import asyncio as _asyncio
    import logging as _lg
    # не глотаем ошибки молча
    try:
        await _asyncio.to_thread(_write_audit_log,
                                 request, status_code, duration_ms)
    except Exception:
        _lg.getLogger("db").exception("audit log failed")
# [/FIX-STAGE:AUDIT-V2]


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # [FIX-STAGE:AUDIT-V2] timing
        import time as _time_audit
        _t0 = _time_audit.monotonic()
        # CSRF: всё, что мутирует данные, требует кастомный заголовок.
        # /api/v2/* использует Bearer — CSRF не применяется.
        if (request.method not in SAFE_METHODS
                and not request.url.path.startswith("/api/v2/")):
            val = request.headers.get(CSRF_HEADER, "")
            if val != CSRF_VALUE:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF check failed"},
                )
            # строгая проверка double-submit.
            if os.getenv("CSRF_STRICT", "1") != "0":
                # local mode: skip double-submit cookie;
                # X-Requested-With already validated above. Otherwise
                # the first POST before any GET would be rejected with 403.
                try:
                    from config import resolve_auth_mode as _ram_csrf
                    from database import DB_ENGINE as _dbe_csrf
                    _auth_mode_csrf = _ram_csrf(_dbe_csrf)
                except Exception:
                    _auth_mode_csrf = "team"
                _PUBLIC_WRITE = {"/api/auth/login", "/api/setup/admin"}
                if _auth_mode_csrf != "local" and request.url.path not in _PUBLIC_WRITE:
                    _csrf_cookie = request.cookies.get("pdb_csrf", "")
                    if not _csrf_cookie:
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "CSRF cookie missing (reload page)"},
                        )
                    _csrf_header = request.headers.get("x-csrf-token", "")
                    if not _csrf_header or not secrets.compare_digest(
                            _csrf_header, _csrf_cookie):
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "CSRF token mismatch"},
                        )
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        # [FIX-STAGE:AUDIT-V2] fire-and-forget
        if request.method in ("POST", "PUT", "DELETE"):
            import asyncio as _aio
            try:
                _aio.create_task(_audit_async(
                    request,
                    getattr(response, 'status_code', 0),
                    (_time_audit.monotonic() - _t0) * 1000.0,
                ))
            except Exception:
                pass
        return response
