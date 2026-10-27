"""V8.1.0: security middleware — CSRF, CSP, X-Frame, nosniff.

Все write-запросы (POST/PATCH/DELETE/PUT) требуют заголовок
`X-Requested-With: DatasetBuilder`, который не выставляется обычными
HTML-формами. Это блокирует классический CSRF на localhost.

CSP настроен максимально строго, но так, чтобы не сломать inline-скрипты
index.html (theme init, i18n fallback) — для них оставлен 'unsafe-inline'.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "DatasetBuilder"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
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
        ip = request.client.host if request.client else ""
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            ip = fwd.split(",")[0].strip()
        details = "%s %s [%s] %.0fms" % (
            request.method, request.url.path[:400],
            status_code, duration_ms,
        )
        db = SessionLocal()
        try:
            db.add(AuditLog(
                timestamp=utcnow(),
                user_ip=ip or None,
                action=request.method,
                details=details[:500],
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


async def _audit_async(request: Request, status_code: int,
                       duration_ms: float) -> None:
    """Обёртка для asyncio.create_task — не блокирует event loop."""
    import asyncio as _asyncio
    await _asyncio.to_thread(_write_audit_log,
                             request, status_code, duration_ms)
# [/FIX-STAGE:AUDIT-V2]


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # [FIX-STAGE:AUDIT-V2] timing
        import time as _time_audit
        _t0 = _time_audit.monotonic()
        # CSRF: всё, что мутирует данные, требует кастомный заголовок.
        if request.method not in SAFE_METHODS:
            val = request.headers.get(CSRF_HEADER, "")
            if val != CSRF_VALUE:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF check failed"},
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
