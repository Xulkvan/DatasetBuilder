from services.auth_service import require_permission
# [PATCH:STAGE6-logs-backend]
from fastapi import Depends, APIRouter
from typing import Optional
from logger import STATUS_LOG, STATUS_LOG_LOCK, log_status
from version import APP_VERSION, AUTHOR

router = APIRouter()

@router.get("/api/logs", dependencies=[Depends(require_permission("logs.read"))])
def get_logs(user_id: Optional[int] = None, limit: int = 300, level: Optional[str] = None, category: Optional[str] = None):
    with STATUS_LOG_LOCK:
        items = list(STATUS_LOG)
    if level:
        items = [x for x in items if x.get("level") == level]
    if category:
        items = [x for x in items if x.get("category") == category]
    if user_id is not None:

        q = q.filter(AuditLog.user_id == user_id)
    limit = max(1, min(2000, int(limit)))
    return {"items": items[-limit:], "total": len(items)}

@router.delete("/api/logs")
def clear_logs():
    with STATUS_LOG_LOCK:
        STATUS_LOG.clear()
    log_status("info", "system", "История статусов очищена")
    return {"status": "ok"}

@router.get("/api/version")
def api_version():
    return {"version": APP_VERSION, "author": AUTHOR}
