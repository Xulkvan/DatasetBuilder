"""services/api_key.py — Unified API key validation (fail-closed).

[PATCH:STAGE1-F-19] Единая точка проверки Bearer-токена для /api/v2/*.
Логика:
  * API_KEY не задан → 503 (fail-closed, F-01);
  * заголовок отсутствует → 401;
  * неверный токен → 403.
"""
import os
import secrets

from fastapi import HTTPException, Request


def validate_api_key(request: Request, *, required: bool = True) -> None:
    expected = (os.getenv("API_KEY") or "").strip()
    if not expected:
        # [PATCH:STAGE1-F-01] fail-closed
        if required:
            raise HTTPException(
                status_code=503,
                detail={
                    "key": "error.apiV2Disabled",
                    "fallback": "API v2 disabled: API_KEY not configured",
                },
            )
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"key": "error.unauthorized",
                    "fallback": "Missing Bearer token"},
        )
    token = auth[7:].strip()
    if not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=403,
            detail={"key": "error.forbidden",
                    "fallback": "Invalid API key"},
        )
