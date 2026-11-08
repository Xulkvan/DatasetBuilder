"""services/startup_tasks.py — [PATCH:STAGE6-F03-4.8] Startup tasks."""
import logging, os, shutil, time
from datetime import datetime
from database import SessionLocal
from models import ImageModel, Setting
from logger import utcnow
from config import RUNS_DIR, SETTING_BACKFILL_DONE
from services.settings_service import set_setting
log = logging.getLogger("db")

def _backfill_v760():
    try:
        db = SessionLocal()
        try:
            flag = db.query(Setting).filter(Setting.key == SETTING_BACKFILL_DONE).first()
            if flag and flag.value == "1": return
            n = 0
            for r in db.query(ImageModel).filter((ImageModel.created_at.is_(None)) | (ImageModel.file_size.is_(None))).yield_per(200):
                if r.created_at is None:
                    try: r.created_at = datetime.fromtimestamp(os.path.getmtime(r.path))
                    except OSError: r.created_at = utcnow()
                if r.file_size is None:
                    try: r.file_size = os.path.getsize(r.path)
                    except OSError: r.file_size = 0
                n += 1
            set_setting(db, SETTING_BACKFILL_DONE, "1")
            if n: log.info("backfill v7.6.0: обновлено %d записей", n)
        finally: db.close()
    except Exception: log.exception("backfill v7.6.0 failed")

def _cleanup_old_runs():
    try:
        if not os.path.isdir(RUNS_DIR): return
        runs = []
        for name in os.listdir(RUNS_DIR):
            path = os.path.join(RUNS_DIR, name)
            if os.path.isdir(path) and name.startswith("train_"): runs.append((path, os.path.getmtime(path)))
        runs.sort(key=lambda x: x[1], reverse=True)
        cutoff = time.time() - 30 * 86400
        deleted = 0
        for path, mtime in runs[5:]:
            if mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                deleted += 1
        if deleted: log.info("Cleanup: удалено %d старых папок обучения", deleted)
    except Exception as e: log.warning("cleanup old runs failed: %s", e)

def _scan_broken_files():
    try:
        from config import STARTUP_SCAN as _mode
        if _mode == "off":
            log.info("startup scan: disabled (STARTUP_SCAN=off)")
            return
        db = SessionLocal()
        try:
            total = broken = 0
            q = db.query(ImageModel.id, ImageModel.path).filter(
                ImageModel.is_deleted.is_(False))
            if _mode == "sample":
                _seen = 0
                for r in q.yield_per(2000):
                    if _seen >= 10000:
                        break
                    _seen += 1
                    total += 1
                    if not r.path or not os.path.exists(r.path):
                        broken += 1
            else:
                for r in q.yield_per(2000):
                    total += 1
                    if not r.path or not os.path.exists(r.path):
                        broken += 1
            if broken:
                log.warning("startup scan (%s): %d битых из %d", _mode, broken, total)
            else:
                log.info("startup scan (%s): %d файлов на месте", _mode, total)
        finally:
            db.close()
    except Exception:
        log.exception("scan broken files failed")

def _restore_active_streams():
    try:
        from services.stream_service import start_stream_worker
        from models import Stream
        db = SessionLocal()
        try:
            rows = db.query(Stream).filter(Stream.is_active.is_(True)).all()
            for s in rows:
                try:
                    start_stream_worker(s.url, s.project_id, fps=float(getattr(s, "capture_fps", 1.0) or 1.0), stream_id=s.id)
                    log.info("stream restored: id=%d url=%s", s.id, s.url)
                except Exception as e: log.warning("stream restore failed id=%d: %s", s.id, e)
        finally: db.close()
    except Exception: log.exception("restore active streams failed")

def _warm_yolo_cache():
    try:
        from services.ml_service import get_active_model_path, _get_yolo_model
        db = SessionLocal()
        try: path = get_active_model_path(db)
        finally: db.close()
        if path:
            _get_yolo_model(path)
            log.info("YOLO warmup: %s", os.path.basename(path))
    except Exception: log.exception("YOLO warmup failed")
