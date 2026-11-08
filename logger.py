import re
from datetime import datetime, timezone
from collections import deque
from typing import Optional, Any
import threading
import logging
import contextvars  # [PATCH:STAGE5-logger-request-id]

log = logging.getLogger("db")

# [PATCH:STAGE4-F-08-json-logs]
import json as _json_log_mod
import os as _os_log_mod
from logging.handlers import RotatingFileHandler as _RotatingFileHandler

_JSON_LOGGERS: dict = {}
_JSON_LOGGER_LOCK = threading.Lock()


def _json_log_path() -> str:
    return _os_log_mod.path.join(
        _os_log_mod.getenv("DATA_ROOT", "."),
        "logs", "app.jsonl",
    )


def _get_json_logger():
    path = _json_log_path()
    if path in _JSON_LOGGERS:
        return _JSON_LOGGERS[path]
    with _JSON_LOGGER_LOCK:
        if path in _JSON_LOGGERS:
            return _JSON_LOGGERS[path]
        try:
            _os_log_mod.makedirs(_os_log_mod.path.dirname(path), exist_ok=True)
            _handler = _RotatingFileHandler(
                path, maxBytes=10 * 1024 * 1024, backupCount=3,
                encoding="utf-8",
            )
            _handler.setFormatter(logging.Formatter("%(message)s"))
            _jlog = logging.getLogger(f"db.jsonl.{abs(hash(path))}")
            _jlog.setLevel(logging.INFO)
            _jlog.propagate = False
            if not _jlog.handlers:
                _jlog.addHandler(_handler)
            _JSON_LOGGERS[path] = _jlog
        except Exception:
            _JSON_LOGGERS[path] = None
        return _JSON_LOGGERS[path]


def _emit_json(entry: dict) -> None:
    try:
        _jlog = _get_json_logger()
        if _jlog is None:
            return
        _jlog.info(_json_log_mod.dumps(entry, ensure_ascii=False))
    except Exception:
        pass


def _reset_json_loggers() -> None:
    """[PATCH:STAGE4-F-08-json-logs] testing helper."""
    with _JSON_LOGGER_LOCK:
        _JSON_LOGGERS.clear()


STATUS_LOG = deque(maxlen=1000)
STATUS_LOG_LOCK = threading.Lock()

# [PATCH:STAGE5-logger-request-id] Stage 5.4 — correlation id.
_request_id_var: contextvars.ContextVar = contextvars.ContextVar(
    "request_id", default=""
)


def set_request_id(rid) -> None:
    """[STAGE5:request-id] Установить request_id текущего контекста."""
    try:
        _request_id_var.set(str(rid) if rid else "")
    except Exception:
        pass


def get_request_id() -> str:
    """[STAGE5:request-id] Получить request_id текущего контекста."""
    try:
        return _request_id_var.get() or ""
    except Exception:
        return ""

_SECRET_PATTERNS = [
    (re.compile(r'(?i)(\bpassword|\bpasswd|\bpwd)\s*[=:]\s*["\']?([^\s,;&"\']{1,256})'), r'\1=***'),
    (re.compile(r'(?i)(\btoken|\bapi_key|\bapikey|\bsecret|\bsecret_key|\baccess_token)\s*[=:]\s*["\']?([^\s,;&"\']{1,256})'), r'\1=***'),
    (re.compile(r'Bearer\s+[A-Za-z0-9._\-]{8,}'), 'Bearer ***'),
    (re.compile(r'(?i)([?&](?:key|token|secret|api_key|apikey|access_token)=)[^\s&"\']{1,256}'), r'\1***'),
]


def _sanitize_secrets(s: str) -> str:
    for pat, repl in _SECRET_PATTERNS:
        try:
            s = pat.sub(repl, s)
        except Exception:
            pass
    return s


_USER_PATH_RE = [
    (re.compile(r'/Users/[^/\s]+'), '/Users/<user>'),
    (re.compile(r'/home/[^/\s]+'), '/home/<user>'),
    (re.compile(r'C:\\Users\\[^\\s]+'), r'C:\\Users\\<user>'),
]

def _sanitize_path(s: str) -> str:
    for pat, repl in _USER_PATH_RE:
        s = pat.sub(repl, s)
    # [PATCH:STAGE1:E1-LOG-SECRET] mask secrets in message
    s = _sanitize_secrets(s)
    return s

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def log_status(level: str, category: str, message: str,
               extra: Optional[dict] = None,
               request_id: Optional[str] = None):  # [PATCH:STAGE5-logger-request-id]
    safe_message = _sanitize_path(str(message))[:800]
    rid = request_id if request_id is not None else get_request_id()
    entry: dict[str, Any] = {
        "ts": utcnow().isoformat(timespec="seconds"),
        "level": (level or "info").lower(),
        "category": category,
        "message": safe_message,
    }
    if rid:
        entry["request_id"] = str(rid)[:16]
    if extra:
        entry["extra"] = {k: _sanitize_path(str(v))[:200] for k, v in extra.items()}
    with STATUS_LOG_LOCK:
        STATUS_LOG.append(entry)
    lvl = {"error": log.error, "warning": log.warning}.get(entry["level"], log.info)
    lvl("[%s] %s", category, safe_message)
    _emit_json(entry)
