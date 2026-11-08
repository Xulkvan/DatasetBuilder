"""services/migrate_service.py — [PATCH:STAGE6-PART2-4.7]"""
import os, logging, threading
from typing import Optional
from sqlalchemy import text, create_engine, event as _sa_event
from sqlalchemy.orm import sessionmaker
from database import engine, DB_ENGINE
from models import *
from logger import log_status, utcnow
from config import DATA_DIR, DATA_ROOT, BASE_DIR

log = logging.getLogger("db")

MIGRATE_STATE = {
    "status": "idle", "stage": "", "message": "", "progress": 0.0,
    "stats": {}, "target_path": "", "env_updated": False,
    "started_at": None, "finished_at": None, "error": None,
}
MIGRATE_LOCK = threading.Lock()
MIGRATE_THREAD = None


















def _migrate_worker(target_path: str, overwrite: bool):
    global MIGRATE_THREAD

    def _set(**kw):
        with MIGRATE_LOCK:
            MIGRATE_STATE.update(kw)

    try:
        _set(status="running", stage="prepare", message="Проверяю состояние…",
             progress=0.0, error=None, started_at=utcnow().isoformat(),
             finished_at=None, stats={}, target_path=target_path, env_updated=False)
        if DB_ENGINE != "mysql":
            raise RuntimeError("Миграция доступна только при DB_ENGINE=mysql")
        # V8.1.0: снимок .env — восстановим, если миграция упадёт
        _env_snap = _snapshot_env()
        if os.path.exists(target_path):
            if not overwrite:
                raise RuntimeError(f"Файл {target_path} уже существует. "
                                   f"Выбери другой путь или разреши перезапись.")
            bak = target_path + ".bak"
            try:
                if os.path.exists(bak):
                    os.remove(bak)
                os.rename(target_path, bak)
            except OSError:
                pass
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        _set(stage="schema", message="Создаю схему SQLite…", progress=2.0)

        target_url = f"sqlite:///{target_path}"
        sqlite_engine = create_engine(
            target_url, connect_args={"check_same_thread": False, "timeout": 60.0},
        )

        @_sa_event.listens_for(sqlite_engine, "connect")
        def _pragma(dbapi_conn, _rec):
            try:
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=OFF")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.execute("PRAGMA busy_timeout=60000")
                cur.close()
            except Exception:
                pass

        Base.metadata.create_all(bind=sqlite_engine)

        SrcSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        DstSession = sessionmaker(bind=sqlite_engine, autoflush=False, autocommit=False)

        model_by_name = {
            "settings": Setting, "projects": Project, "videos": Video,
            "images": ImageModel, "tags": Tag,
            "annotations": Annotation, "image_tags": ImageTag,
        }

        src = SrcSession()
        dst = DstSession()

        _set(stage="count", message="Считаю строки…", progress=5.0)
        counts = {}
        grand_total = 0
        for tname, _ in _MIGRATION_ORDER:
            if tname not in model_by_name:
                continue
            c = _count_rows(src, tname)
            counts[tname] = c
            grand_total += c
        _set(message=f"Всего строк: {grand_total}", progress=8.0, stats={"expected": counts})

        copied = {}
        done_rows = 0
        base_progress = 8.0
        avail = 90.0
        for tname, _ in _MIGRATION_ORDER:
            model_cls = model_by_name.get(tname)
            if model_cls is None:
                continue
            expect = counts.get(tname, 0)
            _set(stage=f"copy:{tname}",
                 message=f"Переношу «{tname}» ({expect} строк)…",
                 progress=base_progress)
            try:
                n = _copy_table_orm(src, dst, model_cls, tname)
            except Exception as e:
                dst.rollback()
                raise RuntimeError(f"Ошибка переноса «{tname}»: {e}")
            dst.commit()
            copied[tname] = n
            done_rows += n
            if grand_total > 0:
                base_progress = 8.0 + (done_rows / grand_total) * avail
            _set(progress=base_progress, stats={"expected": counts, "copied": copied})

        _set(stage="verify", message="Проверяю количество…", progress=98.0)
        mismatches = []
        for tname, _ in _MIGRATION_ORDER:
            if tname not in model_by_name:
                continue
            expect = counts.get(tname, 0)
            got = copied.get(tname, 0)
            if expect != got:
                mismatches.append(f"{tname}: {expect} → {got}")
        if mismatches:
            raise RuntimeError("Расхождение: " + "; ".join(mismatches))

        src.close()
        dst.close()
        sqlite_engine.dispose()

        _set(stage="env", message="Обновляю .env…", progress=99.0)
        try:
            env_path = _update_env_file({
                "DB_ENGINE": "sqlite",
                "DB_PATH": target_path.replace("\\", "/"),
            })
            _set(env_updated=True, message=f".env обновлён: {env_path}")
        except Exception as e:
            log.exception("env update failed")
            _set(env_updated=False, message=f".env НЕ обновлён: {e}")

        _set(status="done", stage="done", progress=100.0,
             message="Миграция завершена. Перезапусти приложение.",
             finished_at=utcnow().isoformat(),
             stats={"expected": counts, "copied": copied})
        log_status("success", "backup",
                   f"Миграция MySQL→SQLite завершена: "
                   f"{sum(copied.values())} строк → {target_path}")
    except Exception as e:
        log.exception("migration failed")
        # [PATCH:STAGE2:E2-MIGRATE-CLEANUP] независимые блоки:
        # ошибка удаления partial не должна блокировать восстановление .bak,
        # и наоборот.
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
                log.info("migration: removed partial SQLite file %s", target_path)
            except OSError:
                log.exception("migration: cannot remove partial file %s", target_path)
        bak = target_path + ".bak"
        if os.path.exists(bak):
            try:
                os.rename(bak, target_path)
                log.info("migration: restored %s from backup", target_path)
            except OSError:
                log.exception("migration: cannot restore from backup %s", bak)
        # V8.1.0: откатываем .env, если он был обновлён
        try:
            _restore_env(_env_snap)
        except Exception:
            pass
        with MIGRATE_LOCK:
            MIGRATE_STATE["status"] = "error"
            MIGRATE_STATE["error"] = str(e)
            MIGRATE_STATE["message"] = f"Ошибка: {e}"
            MIGRATE_STATE["finished_at"] = utcnow().isoformat()
        log_status("error", "backup", f"Миграция MySQL→SQLite упала: {e}")
    finally:
        with MIGRATE_LOCK:
            MIGRATE_THREAD = None

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

# [PATCH:STAGE2-F-02-loop]

def _update_env_file(updates: dict) -> str:
    path = _env_file_path()
    lines = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            lines = []
    keys_handled = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        matched = False
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                keys_handled.add(key)
                matched = True
        if not matched:
            new_lines.append(line if line.endswith("\n") else line + "\n")
    missing = [k for k in updates if k not in keys_handled]
    if missing:
        if new_lines and new_lines[-1].strip():
            new_lines.append("\n")
        new_lines.append("# V7.5.1: добавлено автоматически при миграции\n")
        for k in missing:
            new_lines.append(f"{k}={updates[k]}\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    return path

def _snapshot_env() -> Optional[str]:
    """V8.1.0: снимок .env перед миграцией — восстановим при падении."""
    path = _env_file_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None

def _restore_env(snapshot: Optional[str]) -> None:
    """V8.1.0: восстановление .env из снимка."""
    if snapshot is None:
        return
    try:
        with open(_env_file_path(), "w", encoding="utf-8") as f:
            f.write(snapshot)
        log.info("migrate: .env восстановлен из снимка")
    except OSError:
        log.exception("migrate: не удалось восстановить .env")

def _sqlite_target_path() -> str:
    return os.path.join(DATA_DIR, "dataset.db")

_MIGRATION_ORDER = [
    ("settings", None), ("projects", None), ("videos", None),
    ("images", None), ("tags", None), ("annotations", None), ("image_tags", None),
]

def _count_rows(db, table_name: str) -> int:
    try:
        return int(db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0)
    except Exception:
        return 0

def _copy_table_orm(src_session, dst_session, model_cls, table_name, chunk=500):
    total = 0
    offset = 0
    while True:
        try:
            rows = src_session.query(model_cls).order_by(
                list(model_cls.__table__.primary_key.columns)[0]
            ).offset(offset).limit(chunk).all()
        except Exception:
            log.exception("migrate: cannot read %s offset=%d", table_name, offset)
            raise
        if not rows:
            break
        col_names = [c.name for c in model_cls.__table__.columns]
        for r in rows:
            obj = model_cls()
            for cn in col_names:
                try:
                    setattr(obj, cn, getattr(r, cn, None))
                except Exception:
                    pass
            dst_session.add(obj)
        dst_session.flush()
        src_session.expunge_all()
        total += len(rows)
        offset += len(rows)
        if len(rows) < chunk:
            break
    return total

def _env_file_path() -> str:
    p1 = os.path.join(DATA_ROOT, ".env")
    if os.path.exists(p1):
        return p1
    p2 = os.path.join(BASE_DIR, ".env")
    if os.path.exists(p2):
        return p2
    return p1