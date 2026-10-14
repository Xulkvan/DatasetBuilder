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
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self';"
)


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
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
        return response
