import re
from datetime import datetime, timezone
from collections import deque
from typing import Optional
import threading
import logging

log = logging.getLogger("db")

STATUS_LOG = deque(maxlen=1000)
STATUS_LOG_LOCK = threading.Lock()

_USER_PATH_RE = [
    (re.compile(r'/Users/[^/\s]+'), '/Users/<user>'),
    (re.compile(r'/home/[^/\s]+'), '/home/<user>'),
    (re.compile(r'C:\\Users\\[^\\s]+'), r'C:\\Users\\<user>'),
]

def _sanitize_path(s: str) -> str:
    for pat, repl in _USER_PATH_RE:
        s = pat.sub(repl, s)
    return s

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def log_status(level: str, category: str, message: str, extra: Optional[dict] = None):
    safe_message = _sanitize_path(str(message))[:800]
    entry = {
        "ts": utcnow().isoformat(timespec="seconds"),
        "level": (level or "info").lower(),
        "category": category,
        "message": safe_message,
    }
    if extra:
        entry["extra"] = {k: _sanitize_path(str(v))[:200] for k, v in extra.items()}
    with STATUS_LOG_LOCK:
        STATUS_LOG.append(entry)
    lvl = {"error": log.error, "warning": log.warning}.get(entry["level"], log.info)
    lvl("[%s] %s", category, safe_message)
