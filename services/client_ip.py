"""[PATCH:STAGE1-C5] Client IP resolver, proxy-aware.

За доверенным nginx/traefik включаем TRUST_PROXY_HEADERS=1 — тогда
берём первый IP из X-Forwarded-For (самый внешний клиент) или X-Real-IP.
По умолчанию (0) — используем request.client.host (нельзя подделать).
"""
import os

from fastapi import Request


def get_client_ip(request: Request) -> str:
    if (os.getenv("TRUST_PROXY_HEADERS", "0") or "").strip() == "1":
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
    return request.client.host if request.client else "unknown"
