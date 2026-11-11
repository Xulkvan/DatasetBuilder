"""routers/storage.py — [PATCH:STAGE6-PART2-4.7]"""
import os
from datetime import datetime
import logging
import shutil, threading, subprocess
from typing import Any
from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine, DB_ENGINE, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
from config import DATA_ROOT, UPLOAD_DIR, THUMB_DIR, MODEL_DIR, VIDEO_DIR, BACKUP_DIR, EXPORT_DIR, RUNS_DIR, DATA_DIR
from services.migrate_service import MIGRATE_STATE, MIGRATE_LOCK, _migrate_worker, _sqlite_target_path
from schemas import MigrateIn
from logger import log_status, utcnow
from services.errors import _safe_error_message
from services.image_service import _remove_file_safe

log = logging.getLogger('db')
router = APIRouter()
_SUBPROC_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0

def _dir_size(path: str) -> int:
    total = 0
    if not os.path.isdir(path): return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try: total += os.path.getsize(os.path.join(root, f))
            except OSError: continue
    return total

@router.get("/api/storage/info")
def storage_info(db: Session = Depends(get_db)):
    info: dict[str, Any] = {
        "engine": DB_ENGINE,
        "data_root": DATA_ROOT,
        "can_migrate_to_sqlite": (DB_ENGINE == "mysql"),
        "migration_target": _sqlite_target_path() if DB_ENGINE == "mysql" else None,
        "dirs": {
            "uploads": _dir_size(UPLOAD_DIR),
            "thumbs": _dir_size(THUMB_DIR),
            "models": _dir_size(MODEL_DIR),
            "videos": _dir_size(VIDEO_DIR),
            "backups": _dir_size(BACKUP_DIR),
            "exports": _dir_size(EXPORT_DIR),
            "runs": _dir_size(RUNS_DIR),
        },
    }
    info["total_size"] = sum(int(v) for v in info["dirs"].values())
    if DB_ENGINE == "sqlite":
        db_path = str(engine.url).replace("sqlite:///", "")
        info["db_path"] = db_path
        try:
            info["db_size"] = os.path.getsize(db_path)
            wal = db_path + "-wal"
            shm = db_path + "-shm"
            if os.path.exists(wal):
                info["db_size"] += os.path.getsize(wal)
            if os.path.exists(shm):
                info["db_size"] += os.path.getsize(shm)
        except OSError:
            info["db_size"] = 0
        info["total_size"] += info.get("db_size", 0)
    else:
        try:
            row = db.execute(text(
                "SELECT SUM(data_length + index_length) FROM information_schema.tables "
                "WHERE table_schema = :s"
            ), {"s": DB_NAME}).scalar()
            info["db_size"] = int(row or 0)
            info["db_host"] = f"{DB_HOST}:{DB_PORT}"
            info["db_name"] = DB_NAME
        except Exception:
            info["db_size"] = 0
        info["total_size"] += info.get("db_size", 0)
    return info


@router.get("/api/storage/paths")
def storage_paths():
    return {
        "data_root": DATA_ROOT, "uploads": UPLOAD_DIR, "thumbnails": THUMB_DIR,
        "models": MODEL_DIR, "videos": VIDEO_DIR, "backups": BACKUP_DIR,
    }


@router.post("/api/storage/backup_db")
def storage_backup_db():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if DB_ENGINE == "sqlite":
        db_path = str(engine.url).replace("sqlite:///", "")
        if not os.path.exists(db_path):
            raise HTTPException(404, {"key": "error.dbFileNotFound", "fallback": "Файл БД не найден"})
        out_name = f"dataset_backup_{ts}.db"
        out_path = os.path.join(BACKUP_DIR, out_name)
        # V8.1.0: VACUUM INTO требует SQLite ≥ 3.27 (2019).
        import sqlite3 as _sq
        if _sq.sqlite_version_info < (3, 27, 0):
            raise HTTPException(501,
                f"VACUUM INTO требует SQLite ≥ 3.27 (у вас {_sq.sqlite_version}). "
                f"Скопируйте файл вручную или обновите SQLite.")
        try:
            src = _sq.connect(db_path, timeout=30)
            try:
                src.execute("VACUUM INTO ?", (out_path,))
            finally:
                src.close()
        except Exception as e:
            log.exception("sqlite backup failed")
            raise HTTPException(500, f"Не удалось создать бэкап БД: {_safe_error_message(e)}")
        log_status("success", "backup", f"Бэкап SQLite-БД: {out_name}")
        return FileResponse(out_path, filename=out_name, media_type="application/x-sqlite3")
    dump = shutil.which("mysqldump")
    if not dump:
        raise HTTPException(501, "mysqldump не найден в PATH. Скачивание БД доступно только для SQLite.")
    out_name = f"dataset_backup_{ts}.sql"
    out_path = os.path.join(BACKUP_DIR, out_name)
    try:
        with open(out_path, "wb") as f:
            r = subprocess.run(
                [dump, f"-h{DB_HOST}", f"-P{DB_PORT}", f"-u{DB_USER}",
                 f"-p{DB_PASSWORD}", "--single-transaction", "--quick",
                 "--skip-lock-tables", DB_NAME],
                stdout=f, stderr=subprocess.PIPE, timeout=1800,
                creationflags=_SUBPROC_FLAGS,
            )
        if r.returncode != 0:
            _remove_file_safe(out_path)
            raise HTTPException(500, f"mysqldump: {r.stderr.decode('utf-8', 'replace')[:300]}")
    except HTTPException:
        raise
    except Exception as e:
        _remove_file_safe(out_path)
        raise HTTPException(500, f"mysqldump не выполнен: {_safe_error_message(e)}")
    log_status("success", "backup", f"Бэкап MySQL-БД: {out_name}")
    return FileResponse(out_path, filename=out_name, media_type="application/sql")


@router.get("/api/storage/migrate/status")
def migrate_status():
    with MIGRATE_LOCK:
        state = dict(MIGRATE_STATE)
    state["can_migrate"] = (DB_ENGINE == "mysql")
    state["current_engine"] = DB_ENGINE
    state["target_path"] = state.get("target_path") or _sqlite_target_path()
    if state["status"] == "idle" and DB_ENGINE == "mysql":
        tp = _sqlite_target_path()
        state["target_exists"] = os.path.exists(tp)
    else:
        state["target_exists"] = None
    return state


@router.post("/api/storage/migrate/start")
def migrate_start(payload: MigrateIn = Body(default_factory=MigrateIn)):
    global MIGRATE_THREAD
    if DB_ENGINE != "mysql":
        raise HTTPException(400, {"key": "error.migrationRequiresMysql", "fallback": "Миграция возможна только при DB_ENGINE=mysql"})
    with MIGRATE_LOCK:
        if MIGRATE_STATE["status"] == "running":
            raise HTTPException(409, {"key": "error.migrationRunning", "fallback": "Миграция уже идёт"})
    target = (payload.target_path or "").strip()
    if not target:
        target = _sqlite_target_path()
    target = os.path.abspath(target)
    _data_dir_real = os.path.realpath(DATA_DIR)
    _target_real = os.path.realpath(target)
    if not _target_real.startswith(_data_dir_real + os.sep):
        raise HTTPException(400, {"key": "error.migrationPathOutside", "fallback": "target_path должен быть внутри DATA_DIR"})
    if os.path.exists(target) and not payload.overwrite:
        raise HTTPException(409,
            f"Файл {target} уже существует. Установи overwrite=true, чтобы перезаписать.")
    with MIGRATE_LOCK:
        MIGRATE_STATE.update({
            "status": "running", "stage": "start", "message": "Запускаю миграцию…",
            "progress": 0.0, "stats": {}, "target_path": target,
            "env_updated": False, "started_at": utcnow().isoformat(),
            "finished_at": None, "error": None,
        })
    t = threading.Thread(target=_migrate_worker,
                         args=(target, bool(payload.overwrite)),
                         daemon=True, name="mysql-to-sqlite")
    MIGRATE_THREAD = t
    t.start()
    return {"status": "started", "target_path": target}


@router.post("/api/storage/migrate/reset")
def migrate_reset():
    with MIGRATE_LOCK:
        if MIGRATE_STATE["status"] == "running":
            raise HTTPException(409, {"key": "error.migrationRunning", "fallback": "Миграция идёт"})
        MIGRATE_STATE.update({
            "status": "idle", "stage": "", "message": "", "progress": 0.0,
            "stats": {}, "target_path": "", "env_updated": False,
            "started_at": None, "finished_at": None, "error": None,
        })
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# FFmpeg endpoints
# ---------------------------------------------------------------------------
