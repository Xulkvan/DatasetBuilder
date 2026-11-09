"""services/api_key.py — Unified API key validation (fail-closed).

[PATCH:STAGE1-F-19] Единая точка проверки Bearer-токена для /api/v2/*.
Логика:
  * API_KEY не задан → 503 (fail-closed, F-01);
  * заголовок отсутствует → 401;
  * неверный токен → 403;
  * STAGE1_SEC_V2: API_KEY может быть JSON-map для project scoping.

API_KEY-форматы:
  * plain string   ("secret123") — global admin access (backward compat);
  * JSON map       '{"tokenA": {"projects": [1,2]},
                     "tokenB": {"projects": "*"}}' — scoped.
"""
import json
import logging
import os
import secrets

from fastapi import HTTPException, Request

log = logging.getLogger("db")


def _load_api_key_config() -> dict | str | None:
    raw = (os.getenv("API_KEY") or "").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed:
                return parsed
        except (ValueError, TypeError):
            log.warning(
                "API_KEY starts with '{' but is not valid JSON; "
                "treating as plain string (backward compat)"
            )
    return raw


def validate_api_key(request: Request, *, required: bool = True) -> None:
    cfg = _load_api_key_config()
    if cfg is None:
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
    if isinstance(cfg, str):
        if not secrets.compare_digest(token, cfg):
            raise HTTPException(
                status_code=403,
                detail={"key": "error.forbidden",
                        "fallback": "Invalid API key"},
            )
        return
    _found_scope = None
    for _k, _v in cfg.items():
        if secrets.compare_digest(token, str(_k)):
            _found_scope = _v
            break
    if _found_scope is None:
        raise HTTPException(
            status_code=403,
            detail={"key": "error.forbidden",
                    "fallback": "Invalid API key"},
        )


def get_api_key_scope(request: Request) -> dict | None:
    """None для plain/global API_KEY; dict — для scoped map."""
    cfg = _load_api_key_config()
    if not isinstance(cfg, dict):
        return None
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    for k, v in cfg.items():
        if secrets.compare_digest(token, str(k)):
            return v if isinstance(v, dict) else None
    return None


def require_project_scope(request: Request, project_id: int) -> None:
    scope = get_api_key_scope(request)
    if scope is None:
        return
    projects = scope.get("projects")
    if projects == "*":
        return
    if isinstance(projects, list):
        try:
            allowed = {int(x) for x in projects}
        except (TypeError, ValueError):
            allowed = set()
        if int(project_id) not in allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "key": "error.forbidden",
                    "fallback":
                        "API key not scoped for this project",
                },
            )
        return
    raise HTTPException(
        status_code=403,
        detail={
            "key": "error.forbidden",
            "fallback": "API key has no projects scope",
        },
    )


def get_allowed_projects_scope(request: Request) -> str | list:
    scope = get_api_key_scope(request)
    if scope is None:
        return "*"
    p = scope.get("projects", "*")
    if p == "*":
        return "*"
    if isinstance(p, list):
        return [
            int(x)
            for x in p
            if isinstance(x, (int, str))
            and str(x).lstrip("-").isdigit()
        ]
    return "*"
