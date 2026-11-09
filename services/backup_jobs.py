"""[BACKUP] Async export/import jobs (state machines + threads)."""
import threading
from logger import utcnow

EXPORT_STATE = {
    "status": "idle", "project_id": None, "progress": 0.0,
    "message": "", "zip_path": None, "zip_size": None,
    "started_at": None, "finished_at": None, "error": None,
    "requested_by": None,
}
EXPORT_LOCK = threading.Lock()
EXPORT_EVENT = threading.Event()
EXPORT_STOP = threading.Event()
EXPORT_THREAD = None

IMPORT_STATE = {
    "status": "idle", "progress": 0.0,
    "message": "", "result": None,
    "started_at": None, "finished_at": None, "error": None,
    "warnings": [],
}
IMPORT_LOCK = threading.Lock()
IMPORT_EVENT = threading.Event()
IMPORT_STOP = threading.Event()
IMPORT_THREAD = None


def export_snapshot():
    with EXPORT_LOCK:
        return dict(EXPORT_STATE)


def import_snapshot():
    with IMPORT_LOCK:
        return dict(IMPORT_STATE)


def reset_export_state():
    with EXPORT_LOCK:
        EXPORT_STATE.update({
            "status": "idle", "project_id": None, "progress": 0.0,
            "message": "", "zip_path": None, "zip_size": None,
            "started_at": None, "finished_at": None, "error": None,
            "requested_by": None,
        })
    EXPORT_EVENT.set()


def reset_import_state():
    with IMPORT_LOCK:
        IMPORT_STATE.update({
            "status": "idle", "progress": 0.0, "message": "",
            "result": None, "started_at": None, "finished_at": None,
            "error": None, "warnings": [],
        })
    IMPORT_EVENT.set()


def cancel_import():
    IMPORT_STOP.set()
    IMPORT_EVENT.set()


def start_export_thread(db_session_factory, project_id: int, options: dict,
                        requested_by: str | None = None):
    global EXPORT_THREAD
    with EXPORT_LOCK:
        if EXPORT_STATE["status"] in ("running", "stopping"):
            raise RuntimeError("Export already running")
        EXPORT_STATE.update({
            "status": "running", "project_id": project_id,
            "progress": 0.0, "message": "Starting...",
            "started_at": utcnow().isoformat(), "finished_at": None,
            "error": None, "zip_path": None, "zip_size": None,
            "requested_by": requested_by,
        })
    EXPORT_STOP.clear()
    EXPORT_EVENT.set()

    def _worker():
        global EXPORT_THREAD
        from services.backup_service import export_full_project
        db = db_session_factory()
        try:
            def _progress(stage, done, total):
                pct = (done / total * 100.0) if total else 0.0
                with EXPORT_LOCK:
                    EXPORT_STATE["progress"] = pct
                    EXPORT_STATE["message"] = f"{stage} {done}/{total}"
                EXPORT_EVENT.set()

            result = export_full_project(
                db, project_id,
                include_videos=options.get("include_videos", True),
                include_versions=options.get("include_versions", True),
                include_blur_regions=options.get("include_blur_regions", True),
                include_behavior_validations=options.get("include_behavior_validations", True),
                include_streams=options.get("include_streams", False),
                include_webhooks=options.get("include_webhooks", False),
                progress_cb=_progress,
            )
            with EXPORT_LOCK:
                EXPORT_STATE.update({
                    "status": "done", "progress": 100.0,
                    "message": "Готово",
                    "zip_path": result["zip_path"],
                    "zip_size": result["zip_size"],
                    "finished_at": utcnow().isoformat(),
                })
        except Exception as e:
            with EXPORT_LOCK:
                EXPORT_STATE.update({
                    "status": "error", "error": str(e),
                    "message": f"Ошибка: {e}",
                    "finished_at": utcnow().isoformat(),
                })
        finally:
            db.close()
            with EXPORT_LOCK:
                EXPORT_THREAD = None
            EXPORT_EVENT.set()

    t = threading.Thread(target=_worker, daemon=True, name="backup-export")
    with EXPORT_LOCK:
        EXPORT_THREAD = t
    t.start()


def start_import_thread(db_session_factory, zip_path: str,
                        requested_by: str | None = None):
    global IMPORT_THREAD
    with IMPORT_LOCK:
        if IMPORT_STATE["status"] in ("running", "stopping"):
            raise RuntimeError("Import already running")
        IMPORT_STATE.update({
            "status": "running", "progress": 0.0,
            "message": "Starting...",
            "started_at": utcnow().isoformat(), "finished_at": None,
            "error": None, "result": None, "warnings": [],
        })
    IMPORT_STOP.clear()
    IMPORT_EVENT.set()

    def _worker():
        global IMPORT_THREAD
        from services.backup_service import import_full_project
        db = db_session_factory()
        try:
            with IMPORT_LOCK:
                IMPORT_STATE["message"] = "Валидация и распаковка..."
            IMPORT_EVENT.set()
            result = import_full_project(db, zip_path)
            with IMPORT_LOCK:
                IMPORT_STATE.update({
                    "status": "done", "progress": 100.0,
                    "message": "Готово",
                    "result": result,
                    "warnings": result.get("warnings", []),
                    "finished_at": utcnow().isoformat(),
                })
        except Exception as e:
            with IMPORT_LOCK:
                IMPORT_STATE.update({
                    "status": "error", "error": str(e),
                    "message": f"Ошибка: {e}",
                    "finished_at": utcnow().isoformat(),
                })
        finally:
            db.close()
            try:
                import os as _os_imp
                if _os_imp.path.exists(zip_path):
                    _os_imp.remove(zip_path)
            except OSError:
                pass
            with IMPORT_LOCK:
                IMPORT_THREAD = None
            IMPORT_EVENT.set()

    t = threading.Thread(target=_worker, daemon=True, name="backup-import")
    with IMPORT_LOCK:
        IMPORT_THREAD = t
    t.start()
