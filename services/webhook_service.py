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

RETRIES = 3
BACKOFF = [1.0, 2.0, 4.0]


def _sign(payload: bytes, secret: str) -> str:
    if not secret:
        return ""
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _post_once(url: str, payload: bytes, signature: str) -> bool:
    try:
        import httpx
        headers = {"Content-Type": "application/json",
                   "User-Agent": "DatasetBuilder/Webhooks"}
        if signature:
            headers["X-DatasetBuilder-Signature"] = signature
        with httpx.Client(timeout=10.0) as c:
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
        log.warning("webhook HTTP %s %s", e.code, url)
        return False
    except Exception as e:
        log.warning("webhook urllib error: %s", e)
        return False


def _send_with_retry(url: str, payload: bytes, signature: str) -> bool:
    for attempt in range(RETRIES):
        if _post_once(url, payload, signature):
            return True
        if attempt < RETRIES - 1:
            time.sleep(BACKOFF[attempt])
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
