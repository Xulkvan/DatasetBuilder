"""[STAGE1:webhook_service] Webhooks с HMAC-SHA256 подписью и retry."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Optional

from sqlalchemy.orm import Session

log = logging.getLogger("db")

# [STAGE5:ssrf-webhook]
_WEBHOOK_ALLOW_PRIVATE_WARNED = False


def _allow_private_webhooks() -> bool:
    global _WEBHOOK_ALLOW_PRIVATE_WARNED
    import os as _os
    allow = _os.getenv("WEBHOOK_ALLOW_PRIVATE", "").strip().lower() in ("1", "true", "yes")
    # [PATCH:STAGE1:E1-WEBHOOK-WARN]
    if allow and not _WEBHOOK_ALLOW_PRIVATE_WARNED:
        _WEBHOOK_ALLOW_PRIVATE_WARNED = True
        try:
            import logging as _lg_w
            _lg_w.getLogger("db").warning(
                "WEBHOOK_ALLOW_PRIVATE=1: SSRF protection disabled for webhooks. "
                "Do NOT use in production."
            )
        except Exception:
            pass
    return allow


def _safe_webhook_url(url: str) -> bool:
    try:
        from services.url_safety import is_safe_external_url
        return is_safe_external_url(url)
    except ImportError:
        try:
            import logging as _lg
            _lg.getLogger("db").warning(
                "url_safety module not found — SSRF protection disabled for webhooks")
        except Exception:
            pass
        return True


def _mask_url(url: str) -> str:
    try:
        from urllib.parse import urlparse as _up
        p = _up(str(url))
        if p.query:
            return p.scheme + "://" + (p.hostname or "?") + p.path + "?***"
        return str(url)[:200]
    except Exception:
        return "<url>"

RETRIES = 3
BACKOFF = [1.0, 2.0, 4.0]
import threading as _th_wh
_CIRCUIT_LOCK = _th_wh.Lock()
_FAILED_WEBHOOKS: dict = {}       # url -> {"fails": int, "blocked_until": float}
_CIRCUIT_FAIL_THRESHOLD = 5
_CIRCUIT_BLOCK_SECONDS = 15 * 60


def _circuit_is_open(url: str) -> bool:
    import time as _t
    with _CIRCUIT_LOCK:
        s = _FAILED_WEBHOOKS.get(url)
        if not s:
            return False
        if s.get("blocked_until", 0) > _t.time():
            return True
        if s.get("blocked_until", 0) and s["blocked_until"] <= _t.time():
            # разблокировка по истечении
            _FAILED_WEBHOOKS.pop(url, None)
        return False


def _circuit_record_failure(url: str) -> None:
    import time as _t
    with _CIRCUIT_LOCK:
        s = _FAILED_WEBHOOKS.setdefault(url, {"fails": 0, "blocked_until": 0.0})
        s["fails"] = int(s.get("fails", 0)) + 1
        if s["fails"] >= _CIRCUIT_FAIL_THRESHOLD:
            s["blocked_until"] = _t.time() + _CIRCUIT_BLOCK_SECONDS
            log.warning("webhook circuit opened for %s (fails=%d, blocked for %ds)",
                        _mask_url(url), s["fails"], _CIRCUIT_BLOCK_SECONDS)


def _circuit_record_success(url: str) -> None:
    with _CIRCUIT_LOCK:
        _FAILED_WEBHOOKS.pop(url, None)


def _sign(payload: bytes, secret: str) -> str:
    if not secret:
        return ""
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _post_once(url: str, payload: bytes, signature: str) -> bool:
    # [STAGE5:ssrf-webhook]
    _allow_private = _allow_private_webhooks()
    if not _allow_private and not _safe_webhook_url(url):
        log.warning("webhook blocked (private IP): %s", _mask_url(url))
        return False
    try:
        import httpx
        headers = {"Content-Type": "application/json",
                   "User-Agent": "DatasetBuilder/Webhooks"}
        if signature:
            headers["X-DatasetBuilder-Signature"] = signature
        if _allow_private:
            # WEBHOOK_ALLOW_PRIVATE=1 — dev-режим, pinning отключён.
            with httpx.Client(timeout=10.0) as c:
                r = c.post(url, content=payload, headers=headers)
        else:
            # [STAGE9_DNS_PINNING] pin-IP для http://, double-resolve для https://.
            from services.safe_http_client import get_safe_client
            with get_safe_client(timeout=10.0) as c:
                r = c.post(url, content=payload, headers=headers)
        return 200 <= r.status_code < 300
    except ImportError:
        pass
    except Exception as e:
        log.warning("webhook POST failed: %s", e)
        return False
    # Fallback на urllib
    try:
        import urllib.request
        import urllib.error
        headers = {"Content-Type": "application/json",
                   "User-Agent": "DatasetBuilder/Webhooks"}
        if signature:
            headers["X-DatasetBuilder-Signature"] = signature
        req = urllib.request.Request(url, data=payload, headers=headers,
                                     method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        log.warning("webhook HTTP %s %s", e.code, _mask_url(url))
        return False
    except Exception as e:
        log.warning("webhook urllib error: %s", e)
        return False


def _send_with_retry(url: str, payload: bytes, signature: str) -> bool:
    if _circuit_is_open(url):
        log.warning("webhook circuit open; skipping %s", _mask_url(url))
        return False
    for attempt in range(RETRIES):
        if _post_once(url, payload, signature):
            _circuit_record_success(url)
            return True
        if attempt < RETRIES - 1:
            time.sleep(BACKOFF[attempt])
    _circuit_record_failure(url)
    return False


def dispatch_event(db: Optional[Session], project_id: int,
                   event_type: str, payload: dict) -> int:
    """Отправить webhook всем активным подписчикам. Возвращает число успехов."""
    from database import SessionLocal
    from models import Webhook

    own = db is None
    s = db or SessionLocal()
    try:
        hooks = (s.query(Webhook)
                   .filter(Webhook.project_id == project_id,
                           Webhook.event_type == event_type,
                           Webhook.active.is_(True))
                   .all())
        if not hooks:
            return 0
        body = json.dumps({"event": event_type,
                           "project_id": project_id,
                           "payload": payload},
                          ensure_ascii=False).encode("utf-8")
        ok = 0
        for wh in hooks:
            sig = _sign(body, wh.secret_key or "")
            if _send_with_retry(wh.url, body, sig):
                ok += 1
        if ok:
            log.info("webhook %s: sent to %d/%d", event_type, ok, len(hooks))
        return ok
    except Exception:
        log.exception("webhook dispatch failed")
        return 0
    finally:
        if own:
            s.close()
