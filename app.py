# [PATCH:STAGE7-ensure-schema]
"""
Dataset Builder — V14.X.X
============================================================
Backend: FastAPI + (MySQL | PestgreeSQL | SQLite) + YOLO + SAM + ffmpeg.
Frontend: index.html + style.css + app.js (лежат рядом, отдаются как статика).

Запуск:
    1) MySQL:  CREATE DATABASE pig_dataset CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
       SQLite: ничего не нужно, файл data/dataset.db создастся сам
    2) pip install -r requirements.txt
    3) python run.py
Открыть: http://localhost:8000

Переменные окружения (.env):
    DB_ENGINE=sqlite | mysql
    DB_PATH=data/dataset.db             (только SQLite)
    DB_USER / DB_PASSWORD / DB_HOST / DB_PORT / DB_NAME   (только MySQL)
    DATA_ROOT — куда писать uploads, thumbs, models, videos, backups, exports, runs, data
    HOST / PORT / DEBUG
    MAX_UPLOAD_MB / MAX_IMPORT_MB / MAX_VIDEO_MB / MAX_VIDEO_FRAMES
"""

import os
import re
import io
import csv
import sys
import json
import uuid
import time
import gc
import base64
import random
import shutil
import zipfile
import tempfile
import threading
import subprocess
# Windows: не показывать консольные окна для дочерних процессов (ffmpeg, yolo, mysqldump)
_SUBPROC_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

# CREATE_NEW_PROCESS_GROUP есть только на Windows — на Linux/macOS
# это AttributeError. Берём через getattr с дефолтом 0.
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
import asyncio
import logging
import urllib.request
import urllib.error
import uvicorn
from services.url_safety import is_safe_external_url

from services.project_access import check_project_access


import xml.etree.ElementTree as ET

from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from functools import lru_cache
from io import StringIO
from typing import Optional, Any

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Depends, Body, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, Response, JSONResponse
from pydantic import BaseModel, Field
from PIL import Image

Image.MAX_IMAGE_PIXELS = 50_000_000

from sqlalchemy import inspect, text, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database import SessionLocal, Base, engine, get_db, DB_ENGINE, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME


# V13.1.0: восстановленные сервисы

from models import Project, ImageModel, Annotation, Keypoint, Setting, Tag, ImageTag, Video, Stream, Webhook

from schemas import *
from config import *
from config import _HEX_COLOR_RE
from config import _norm_behavior, _norm_animal_id
from logger import log_status, utcnow

from services.settings_service import get_setting, set_setting, get_trash_ttl_days
from services.behavior_service import predict_behavior_from_keypoints
from services.ffmpeg_service import (
    _check_ffmpeg, _probe_video, _extract_frames, _ffmpeg_os_info,
    _FFMPEG_PATHS, _FFMPEG_LOCK,
)
from services.bootstrap_service import (
    BOOTSTRAP_STATE, BOOTSTRAP_LOCK, BOOTSTRAP_EVENT, _MODEL_ACTIVATION_LOCK,
    _bootstrap_snapshot, _download_model_worker,
    _bootstrap_default_model_if_empty,
)
# module-ref for BOOTSTRAP_THREAD
from services import bootstrap_service as _bootstrap_svc
from services.trash_service import (
    cleanup_expired_trash,
    cleanup_expired_data,
    _start_trash_cleaner_thread,
)
from services.train_service import (
    prepare_training_dataset_pose,
)
from services.file_service import (
    _safe_model_path, _sanitize_model_name, _unique_model_name_from_disk, _is_simple_filename,
    sanitize_display_name, _unique_name_mem,
    _detect_image_format, _split_name_ext, letterbox,
    _open_image_safe,
    _is_image_ext,
)
from services.image_service import (
    _remove_file_safe, _queue_thumb, _invalidate_stats_cache, _invalidate_phash_index, _iou_xywh, dedup_boxes,
    phash_hex, _hex_to_int, _hamming_int,
    _get_phash_index, _find_duplicates_via_index,
)
# shared error utilities
from services.errors import _safe_error_message, _db_commit_safe
# startup tasks
from services.startup_tasks import (
    _backfill_v760, _cleanup_old_runs, _scan_broken_files,
    _restore_active_streams, _warm_yolo_cache
)
from services.external_import_service import (
    _labelbox_to_coco, _scale_to_coco, _coco_to_zip,
    _download_to_file, _http_get_json, _http_post_json
)
from services.zip_import_service import (
    parse_coco, parse_yolo, parse_cvat, parse_label_studio, detect_format,
    IMPORT_PROGRESS,
    # re-exports for backward compat with tests that do `from app import _safe_extract_zip` (test_path_traversal.py / test_zip_bomb.py).
    _safe_extract_zip,
    _collect_image_files,
    _update_import_progress,
)
# Thin delegate:
# wrap impl in a local function so future signature/behaviour changes
# don't break `from app import _process_dataset_zip` in other modules.
from services.zip_import_service import _process_dataset_zip as _process_dataset_zip_impl


def _process_dataset_zip(zip_path, project_id, db, cancel_event=None,
                         source="upload"):
    """Thin delegate to services.zip_import_service._process_dataset_zip."""
    return _process_dataset_zip_impl(zip_path, project_id, db,
                                     cancel_event, source)

from services.rate_limiter import (
    _rate_limit,
    _limiter_import, _limiter_autolabel, _limiter_train,
)
from services.ml_service import (
    _YOLO_CACHE, get_active_model_path, get_active_pose_model_path,
    _get_yolo_model, _clear_yolo_cache,
    _autolabel_batch_predict, _save_autolabel_no_commit,
    _is_duplicate_box, _load_boxes_xywh, _load_annotations,
    _count_annotations_with_skeleton,
    _resolve_target_class_ids,
    _get_model_classes_cached, _invalidate_model_classes_cache,
    _is_pose_model_name, _is_single_model_mode,
)
from services.sam_service import (
    _SAM_CACHE, get_sam_model_name, _get_sam_model, _run_sam_predict,
)
from services.track_service import (
    TRACK_STATE, TRACK_LOCK, TRACK_STOP, TRACK_EVENT,
    _track_snapshot, _track_worker,
)
from services.motion_service import _check_motion, _check_motion_batch

from logger import (
    log_status, utcnow,
)

try:
    from prometheus_fastapi_instrumentator import Instrumentator
    _Instrumentator: Any = Instrumentator
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _Instrumentator = None
    _PROMETHEUS_AVAILABLE = False

from services.metrics import (
    images_uploaded_total as _images_uploaded_total,
    imports_completed_total as _imports_completed_total,
    train_runs_total as _train_runs_total,
    pipeline_runs_total as _pipeline_runs_total,
    autolabel_box_total as _autolabel_box_total,
)

# V13.1.1: создаём таблицы после импорта моделей.
# Раньше это было в database.py, но там циклический импорт с models.
Base.metadata.create_all(bind=engine)
print(f"[db] create_all: таблицы проверены/созданы")

log = logging.getLogger("db")


# функции вынесены в services/export_service.py
from services.export_service import (
    _build_letterbox_meta,
    _split_images,
    _kp_yolo_row,
    _project_has_keypoints,
)


def _chunks(seq, n: int = 500):
    """Разбивает последовательность на чанки по n (лимит SQLite — 999 параметров)."""
    for i in range(0, len(seq), n):
        yield seq[i:i + n]

@contextmanager
def _atomic_zip(zip_path: str):
    """Atomic zip writer: пишет в .tmp, os.replace при успехе."""
    import uuid as _uuid_atomic
    _tmp = zip_path + f".tmp_{_uuid_atomic.uuid4().hex[:8]}"
    _zf = None
    try:
        _zf = zipfile.ZipFile(_tmp, "w", zipfile.ZIP_DEFLATED)
        yield _zf
        _zf.close()
        _zf = None
        os.replace(_tmp, zip_path)
    except Exception:
        if _zf is not None:
            try:
                _zf.close()
            except Exception:
                pass
        try:
            if os.path.exists(_tmp):
                os.remove(_tmp)
        except OSError:
            pass
        raise

# ============================================================================
# V13.1.1: ensure_schema — миграции для существующих БД.
# Добавляет недостающие колонки в старые таблицы (V7 → V13).
# Безопасно при повторных вызовах: проверяет существование колонки.
# ============================================================================
_MIGRATIONS = [
    ("images", "is_deleted", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("images", "deleted_at", "DATETIME NULL"),
    ("images", "phash", "VARCHAR(16) NULL"),
    ("images", "is_hard", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("annotations", "confidence", "FLOAT NULL"),
    ("annotations", "is_frozen", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("annotations", "behavior", "VARCHAR(32) NULL"),
    ("annotations", "animal_id", "INT NULL"),
    ("annotations", "behavior_source", "VARCHAR(16) NULL"),
    ("projects", "created_at", "DATETIME NULL"),
    ("projects", "is_deleted", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("projects", "deleted_at", "DATETIME NULL"),
    ("projects", "object_class", "VARCHAR(128) NOT NULL DEFAULT 'pig'"),
    ("projects", "object_class_source", "VARCHAR(16) NOT NULL DEFAULT 'list'"),
    ("projects", "trash_ttl_days_override", "INT NULL"),
    ("projects", "thumbnail_size", "INT NULL"),
    ("projects", "default_zoom", "FLOAT NULL"),
    ("images", "video_id", "INT NULL"),
    ("images", "frame_index", "INT NULL"),
    ("images", "created_at", "DATETIME NULL"),
    ("images", "file_size", "INT NULL"),
    ("images", "timestamp_sec", "FLOAT NULL"),
    ("projects", "random_seed", "INT NOT NULL DEFAULT 42"),
    ("projects", "auto_blur_enabled", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("projects", "auto_blur_classes", "TEXT NULL"),
    ("streams", "capture_fps", "FLOAT NOT NULL DEFAULT 1.0"),
    ("projects", "data_retention_days", "INT NOT NULL DEFAULT 0"),
    ("images", "original_width",  "INT NULL"),
    ("images", "original_height", "INT NULL"),
    ("dataset_versions", "keypoint_count", "INTEGER DEFAULT 0"),
    ("dataset_versions", "behavior_count", "INTEGER DEFAULT 0"),
    ("users", "must_change_password", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "full_name", "VARCHAR(128) NULL"),
    ("users", "temp_password", "VARCHAR(128) NULL"),
    ("audit_logs", "user_id", "INTEGER NULL"),  # [STAGE2:audit-migrations-fixed]
    ("audit_logs", "username", "VARCHAR(64) NULL"),  # [STAGE2:audit-migrations-fixed]
    ("images", "assigned_to", "INTEGER NULL"),
    ("images", "assigned_at", "DATETIME NULL"),
    ("images", "review_status", "VARCHAR(16) NOT NULL DEFAULT 'unassigned'"),
    ("images", "reviewed_by", "INTEGER NULL"),
    ("images", "reviewed_at", "DATETIME NULL"),
    ("images", "review_comment", "TEXT NULL"),
    ("images", "revision", "INTEGER NOT NULL DEFAULT 1"),
] # [PATCH:FIX_MIGRATIONS_LIST_V2]
# [STAGE0:auth-migrations-list]


# ─────────────────────────────────────────────────────────────────────────
# _POST_CREATE_MIGRATIONS — единый список DDL для таблиц/колонок, которые
# нельзя выразить в _MIGRATIONS (создание таблиц, ALTER с пересозданием).
# ─────────────────────────────────────────────────────────────────────────
def _migrate_project_keypoint_schemas():
    try:
        with engine.begin() as _conn:
            if DB_ENGINE == "sqlite":
                _conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS project_keypoint_schemas ("
                    "  id INTEGER PRIMARY KEY,"
                    "  project_id INTEGER UNIQUE REFERENCES projects(id),"
                    "  schema_json TEXT"
                    ")"
                ))
            else:
                _conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS project_keypoint_schemas ("
                    "  id INT AUTO_INCREMENT PRIMARY KEY,"
                    "  project_id INT UNIQUE,"
                    "  schema_json TEXT,"
                    "  FOREIGN KEY (project_id) REFERENCES projects(id)"
                    ")"
                ))
    except Exception as _e:
        log.warning("migrate project_keypoint_schemas skipped: %s", _e)


def _migrate_streams():
    try:
        with engine.begin() as _conn:
            if DB_ENGINE == "sqlite":
                _conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS streams ("
                    "  id INTEGER PRIMARY KEY,"
                    "  project_id INTEGER REFERENCES projects(id),"
                    "  url VARCHAR(512),"
                    "  name VARCHAR(128),"
                    "  is_active TINYINT(1) NOT NULL DEFAULT 1"
                    ")"
                ))
            else:
                _conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS streams ("
                    "  id INT AUTO_INCREMENT PRIMARY KEY,"
                    "  project_id INT,"
                    "  url VARCHAR(512),"
                    "  name VARCHAR(128),"
                    "  is_active TINYINT(1) NOT NULL DEFAULT 1,"
                    "  FOREIGN KEY (project_id) REFERENCES projects(id)"
                    ")"
                ))
    except Exception as _e:
        log.warning("migrate streams skipped: %s", _e)


def _migrate_is_stream_frame():
    try:
        _insp = inspect(engine)
        _img_cols = {c["name"] for c in _insp.get_columns("images")}
        if "is_stream_frame" not in _img_cols:
            with engine.begin() as _conn:
                if DB_ENGINE == "sqlite":
                    _conn.execute(text(
                        'ALTER TABLE "images" ADD COLUMN '
                        '"is_stream_frame" TINYINT(1) NOT NULL DEFAULT 0'
                    ))
                else:
                    _conn.execute(text(
                        "ALTER TABLE `images` ADD COLUMN "
                        "`is_stream_frame` TINYINT(1) NOT NULL DEFAULT 0"
                    ))
            log.info("migrate: images.is_stream_frame added")
    except Exception as _e:
        log.warning("migrate images.is_stream_frame skipped: %s", _e)


def _migrate_image_locks_session_id():
    try:
        with engine.begin() as _conn:
            if DB_ENGINE == "sqlite":
                _conn.execute(text("ALTER TABLE image_locks RENAME TO image_locks_old"))
                _conn.execute(text(
                    "CREATE TABLE image_locks ("
                    "  image_id INTEGER PRIMARY KEY,"
                    "  user_id INTEGER NOT NULL,"
                    "  session_id INTEGER,"
                    "  acquired_at DATETIME NOT NULL,"
                    "  expires_at DATETIME NOT NULL,"
                    "  FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE,"
                    "  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,"
                    "  FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE"
                    ")"
                ))
                _conn.execute(text("DROP TABLE image_locks_old"))
            elif DB_ENGINE == "postgres":
                _conn.execute(text("ALTER TABLE image_locks ALTER COLUMN session_id DROP NOT NULL"))
            else:
                _conn.execute(text("ALTER TABLE image_locks MODIFY session_id INT NULL"))
    except Exception as e:
        log.warning("migrate image_locks session_id skipped: %s", e)


_POST_CREATE_MIGRATIONS = [
    ("project_keypoint_schemas", _migrate_project_keypoint_schemas),
    ("streams", _migrate_streams),
    ("is_stream_frame", _migrate_is_stream_frame),
    ("image_locks_session_id", _migrate_image_locks_session_id),
]


def ensure_schema():
    """Миграции для существующих БД. Идемпотентна."""
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    except Exception:
        log.exception("ensure_schema: cannot inspect DB")
        return

    for table, column, ddl in _MIGRATIONS:
        if table not in tables:
            continue
        try:
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
        except Exception:
            continue
        if column in existing_cols:
            continue
        try:
            with engine.begin() as conn:
                if DB_ENGINE == "sqlite":
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
                elif DB_ENGINE == "postgres":
                    _pg_ddl = ddl
                    _pg_ddl = re.sub(r"TINYINT\(1\)", "SMALLINT", _pg_ddl)
                    _pg_ddl = re.sub(r"\bDATETIME\b", "TIMESTAMP", _pg_ddl)
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {_pg_ddl}'))
                else:
                    conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}"))
            log.info("migrate: %s.%s added", table, column)
        except Exception as e:
            log.warning("migrate: %s.%s skipped (%s)", table, column, e)

    for _mig_name, _mig_fn in _POST_CREATE_MIGRATIONS:
        try:
            _mig_fn()
        except Exception as _mig_err:
            log.warning("post-create migration %s failed: %s", _mig_name, _mig_err)

ensure_schema()


# ============================================================================
# CREATE TABLE IF NOT EXISTS
# project_keypoint_schemas. Дополняет Base.metadata.create_all для случаев,
# когда модель ProjectKeypointSchema была добавлена после первичной инициализации.
# ============================================================================


# ============================================================================
# is_stream_frame в images + CREATE TABLE streams.
# ============================================================================


try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# OpenCV для проверки motion_blur
try:
    import cv2
except ImportError:
    cv2 = None

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
_handlers = []
if sys.stderr is not None:
    try:
        sys.stderr.write("")
        _handlers.append(logging.StreamHandler())
    except Exception:
        pass
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=_handlers or [logging.NullHandler()],
)
log = logging.getLogger("db")

def _norm_mode(m):
    return m if m in ("add", "replace") else "add"


# ModelCache moved to services


# ---------------------------------------------------------------------------
from version import APP_VERSION, AUTHOR

# Константы
# ---------------------------------------------------------------------------
# APP_VERSION берется из version.py
# AUTHOR берется из version.py

DEBUG_MODE = os.getenv("DEBUG", "0") == "1"

# Все пути — из config.py (единый источник правды).
# BASE_DIR / DATA_ROOT / UPLOAD_DIR / MODEL_DIR / THUMB_DIR и т.д.
# уже импортированы через `from config import *` в шапке файла.
INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")
STYLE_CSS_PATH = os.path.join(BASE_DIR, "style.css")
APP_JS_PATH = os.path.join(BASE_DIR, "app.js")
I18N_JS_PATH = os.path.join(BASE_DIR, "i18n.js")


# Дубли устранены в Stage 6.4.
# Ниже перечисленные константы теперь берутся из config.py:
#   FIXED_SIZE, LETTERBOX_FILL, THUMB_SIZE
#   CONF_THRESHOLD, DEDUP_IOU_THRESHOLD, PHASH_DUPLICATE_THRESHOLD,
#   SIMILAR_DEFAULT_THRESHOLD
#   SETTING_* (8 шт.), DEFAULT_TRASH_TTL_DAYS, DEFAULT_SAM_MODEL,
#   VALID_SAM_MODELS, SAM_MIN_POINTS, SAM_MAX_POINTS,
#   ACTIVE_LEARNING_NEW_THRESHOLD
#   KEYPOINT_SCHEMA, KEYPOINT_NAMES, KEYPOINT_VALID
#   DEFAULT_OBJECT_CLASS, MAX_OBJECT_CLASS_LEN,
#   BEHAVIORS, MAX_ANIMAL_ID
#   VALID_THUMB_SIZES, VALID_DEFAULT_ZOOMS
#   VIDEO_EXTS, VALID_EXTRACT_FPS, DEFAULT_EXTRACT_FPS
#   MAX_VIDEO_*, MAX_UPLOAD_*, MAX_IMPORT_*, MAX_EXTRACTED_* (все *_MB/_BYTES/_FRAMES)
#   MAX_EPOCHS, MAX_EPOCH_PLAUSIBLE, MAX_TRAIN_LOG_LINES, MAX_FREEZE_LAYERS
#   BATCH_IMPORT_CHUNK, BATCH_AUTOLABEL_COMMIT_EVERY
#   MIN_BOX_AREA, MAX_OVERLAP_IOU, NESTED_RATIO, MAX_ASPECT
#
# Источник правды — config.py. Любые правки значений — только там.
#
# _norm_behavior и _norm_animal_id импортируются явно (см. шапку файла),
# так как имена с `_` не приходят через `from config import *`.
#
# ВАЖНО: BASE_DIR, DATA_ROOT, UPLOAD_DIR, MODEL_DIR и др. пути
# остаются здесь — они frozen-aware (PyInstaller), в config.py этого нет.


# File name helpers moved to services/file_service.py



# ---------------------------------------------------------------------------
# Определение формата картинок
# ---------------------------------------------------------------------------
# File magic & open helpers moved to services/file_service.py

# ---------------------------------------------------------------------------
# Безопасная распаковка zip
# ---------------------------------------------------------------------------
# moved to zip_import_service

# ---------------------------------------------------------------------------
# Converters к COCO
# ---------------------------------------------------------------------------
# moved _labelbox_to_coco
# moved _scale_to_coco
# moved _coco_to_zip
def _mask_exc(e) -> str:
    """Маскирует query-параметры (возможные API-ключи) в тексте исключения."""
    try:
        msg = str(e) if e is not None else ""
    except Exception:
        return "<exception>"
    msg = re.sub(r'\?[^\s"\']+', '?***', msg)
    return msg[:200]

# ---------------------------------------------------------------------------
# Обучение
# ---------------------------------------------------------------------------
# Training state & thread moved to
# services/train_service.py to break the app.py <-> routers/api_v2.py cycle.
from services.train_service import (
    TRAIN_STATE, TRAIN_LOCK, TRAIN_EVENT,
    _train_reset, _train_snapshot,
    prepare_training_dataset,
    _handle_train_line,  # noqa: F401  (kept for API compatibility)
    run_training_thread as _run_training_thread,
)
# TRAIN_PROCESS is rebindable inside
# run_training_thread — read via module, not via from-import.
from services import train_service as _train_svc



# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

# moved _restore_active_streams
# moved _warm_yolo_cache
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        n = cleanup_expired_trash(db)
        if n:
            log.info("Удалено устаревших объектов из корзины: %d", n)
        # retention при старте
        try:
            n2 = cleanup_expired_data(db)
            if n2:
                log.info("Retention: удалено %d изображений", n2)
        except Exception:
            log.exception("retention cleanup on startup failed")
    finally:
        db.close()
    try:
        _check_ffmpeg()
        if _FFMPEG_PATHS.get("ok"):
            log.info("ffmpeg: %s", _FFMPEG_PATHS.get("ffmpeg"))
        else:
            log.warning("ffmpeg не найден — извлечение кадров из видео недоступно")
    except Exception:
        log.exception("ffmpeg pre-check failed")
    # warn about team-mode + non-secure cookies
    try:
        from config import resolve_auth_mode as _ram_life, SESSION_COOKIE_SECURE as _scs_life
        from database import DB_ENGINE as _dbe_life
        if _ram_life(_dbe_life) == 'team':
            _scs_low = str(_scs_life).lower()
            if _scs_low not in ('1', 'true', 'yes', '0', 'false', 'no'):
                log.warning(
                    'TEAM MODE: SESSION_COOKIE_SECURE=%r (auto). '
                    'HTTPS is strongly recommended. Set '
                    'SESSION_COOKIE_SECURE=1 if behind HTTPS proxy, '
                    'or =0 only for trusted LAN.',
                    _scs_life,
                )
    except Exception:
        pass
    _start_trash_cleaner_thread()
    # Stage 3.10: retention cleaner moved to trash_service.
    from services.trash_service import start_retention_cleaner_thread
    start_retention_cleaner_thread()
    # Восстановление активных стримов
    threading.Thread(target=_restore_active_streams, daemon=True,
                     name="stream-restore").start()
    t = threading.Thread(target=_bootstrap_default_model_if_empty,
                         daemon=True, name="model-bootstrap")
    t.start()
    # V7.9.3: фоновые задачи — не блокируем старт приложения.
    threading.Thread(target=_backfill_v760, daemon=True,
                     name="backfill-v760").start()
    threading.Thread(target=_warm_yolo_cache, daemon=True,
                     name="yolo-warmup").start()
    # V8.3.1: фоновая проверка целостности файлов.
    threading.Thread(target=_scan_broken_files, daemon=True,
                     name="broken-scan").start()
    threading.Thread(target=_cleanup_old_runs, daemon=True,
                     name="runs-cleanup").start()
    def _cache_cleanup_loop():
        while True:
            time.sleep(60)
            try:
                _YOLO_CACHE.cleanup()
                _SAM_CACHE.cleanup()
            except Exception:
                pass

    threading.Thread(target=_cache_cleanup_loop, daemon=True, name="model-cache-cleanup").start()

    # Stage 5.11 — startup diagnostics
    try:
        from config import (
            resolve_auth_mode as _ram_diag,
            SESSION_COOKIE_SECURE as _scs_diag,
        )
        from database import DB_ENGINE as _dbe_diag
        import os as _os_diag
        _mode_diag = _ram_diag(_dbe_diag)
        _scs_diag_low = str(_scs_diag).lower()
        if _mode_diag == "team" and _scs_diag_low not in ("1", "true", "yes"):
            log.warning(
                "STARTUP: AUTH_MODE=team, SESSION_COOKIE_SECURE=%r — "
                "HTTPS strongly recommended (set SESSION_COOKIE_SECURE=1).",
                _scs_diag,
            )
        if _mode_diag == "team" and not (_os_diag.getenv("API_KEY") or "").strip():
            log.info(
                "STARTUP: AUTH_MODE=team, API_KEY not set → /api/v2/* returns 503 "
                "(fail-closed)."
            )
        if _os_diag.getenv("DEBUG", "0").strip() == "1" and \
                _os_diag.getenv("ENV", "").strip().lower() == "prod":
            log.warning("STARTUP: DEBUG=1 while ENV=prod — turn DEBUG off.")
        if (_os_diag.getenv("METRICS_AUTH", "off").strip().lower() == "off"
                and _os_diag.getenv("ENV", "").strip().lower() == "prod"):
            log.warning(
                "STARTUP: METRICS_AUTH=off while ENV=prod — /api/metrics is public. "
                "Set METRICS_AUTH=basic and METRICS_BASIC_USER/PASSWORD."
            )
        if (_os_diag.getenv("WEBHOOK_ALLOW_PRIVATE", "0").strip() in ("1", "true")):
            log.warning(
                "STARTUP: WEBHOOK_ALLOW_PRIVATE=1 — SSRF protection for webhooks "
                "disabled. Do NOT use in production."
            )
    except Exception:
        pass

    log_status("info", "system", f"Dataset Builder {APP_VERSION} запущен")
    yield
    # V8.1.0: корректно завершаем пул миниатюр.
    try:
        from services.image_service import shutdown_thumb_pool
        shutdown_thumb_pool()
    except Exception:
        log.exception("thumb pool shutdown failed")
    log_status("info", "system", "Приложение останавливается")


# moved to services/errors.py
_OPENAPI_TAGS = [
    {"name": "api_v2", "description": "B2B API v2 (Bearer auth)."},
    {"name": "projects", "description": "Проекты: CRUD, настройки, версии."},
    {"name": "images", "description": "Изображения: загрузка, список, разметка."},
    {"name": "ml", "description": "ML: авторазметка, SAM, pose, поведение."},
    {"name": "system", "description": "Система: логи, версия, здоровье."},
    {"name": "webhooks", "description": "Webhook-подписки."},
]


app = FastAPI(
    title=f"Dataset Builder {APP_VERSION}",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_tags=_OPENAPI_TAGS,
)

if _PROMETHEUS_AVAILABLE:
    try:
        _Instrumentator().instrument(app).expose(
            app, endpoint="/api/metrics", include_in_schema=False,
        )
        log.info("Prometheus /api/metrics enabled")
    except Exception as _e_prom:
        log.warning("Prometheus instrumentation failed: %s", _e_prom)


# Basic-auth gate for /api/metrics
@app.middleware("http")
async def _metrics_basic_auth(request: Request, call_next):
    if request.url.path != "/api/metrics":
        return await call_next(request)
    if not _PROMETHEUS_AVAILABLE:
        return await call_next(request)
    try:
        from config import (METRICS_AUTH as _ma, METRICS_BASIC_USER as _mbu,
                            METRICS_BASIC_PASSWORD as _mbp)
        if (_ma or '').lower() != 'basic':
            return await call_next(request)
        if not _mbu or not _mbp:
            log.warning('METRICS_AUTH=basic but METRICS_BASIC_USER/PASSWORD unset')
            return JSONResponse(status_code=503,
                                content={'detail': 'metrics auth misconfigured'})
        _auth = request.headers.get('Authorization', '')
        if not _auth.startswith('Basic '):
            return JSONResponse(
                status_code=401,
                content={'detail': 'auth required'},
                headers={'WWW-Authenticate': 'Basic realm="metrics"'},
            )
        import base64 as _b64m
        try:
            _decoded = _b64m.b64decode(_auth[6:]).decode('utf-8')
        except Exception:
            return JSONResponse(status_code=403,
                                content={'detail': 'bad credentials'})
        if ':' not in _decoded:
            return JSONResponse(status_code=403,
                                content={'detail': 'bad credentials'})
        _user_m, _pass_m = _decoded.split(':', 1)
        import secrets as _secm
        if not (_secm.compare_digest(_user_m, _mbu)
                and _secm.compare_digest(_pass_m, _mbp)):
            return JSONResponse(status_code=403,
                                content={'detail': 'invalid credentials'})
        return await call_next(request)
    except Exception:
        log.exception('metrics auth middleware error')
        return JSONResponse(status_code=500,
                            content={'detail': 'metrics auth error'})

# Единый источник auth-зависимостей — services.auth_service.
# Локальные дубли (auth-mode helper + user/permission deps) удалены.
from fastapi import Request, Depends, HTTPException, Body, Response
from fastapi.responses import JSONResponse


import os

from services.auth_service import get_current_user, require_permission

@app.middleware("http")
async def _global_auth_middleware(request: Request, call_next):
    # Убедиться, что request_id
    # установлен ДО любых логов (defensive: если add_request_id
    # окажется inner — здесь fallback).
    try:
        _ensure_request_id(request)
    except Exception:
        pass
    path = request.url.path

    # 1. Всегда пытаемся прочитать сессию (даже для публичных путей)
    u = request.cookies.get("pdb_session")
    # preserve user context set by _v2_api_key_guard
    if u and getattr(request.state, "user", None) is None:
        db = SessionLocal()
        try:
            from services.auth_service import resolve_session
            user = resolve_session(db, u)
            if user:
                request.state.user = user
        finally:
            db.close()

    # 2. Локальный режим — пускаем без авторизации
    if resolve_auth_mode(DB_ENGINE) == "local":
        request.state.user = {"id": 0, "username": "local",
                              "role": "admin", "local": True}
        # гарантируем pdb_csrf cookie в local mode
        resp = await call_next(request)
        try:
            if not request.cookies.get("pdb_csrf"):
                from services.auth_service import set_csrf_cookie
                set_csrf_cookie(resp, request)
        except Exception:
            pass
        return resp

    # 3. Публичные пути
    # /api/health публичен для Docker healthcheck.
    if (path in ("/api/auth/login", "/api/auth/me", "/api/auth/status",
                 "/api/setup/status", "/api/setup/admin",
                 "/api/health", "/api/metrics")
        or path.startswith("/js/") or path.endswith(".css")
        or path in ("/", "/favicon.ico", "/api/version")
        or path.startswith("/docs")
        or path.startswith("/api/v2/")):  # v2 защищён API_KEY
        return await call_next(request)

    # 4. Требуем авторизацию
    if not getattr(request.state, "user", None):
        if path.startswith("/api/"):
            try:
                _rid_401 = getattr(request.state, "request_id", "?")
                log.warning(
                    "auth-401: rid=%s path=%s method=%s has_cookie=%s auth_mode=%s",
                    _rid_401, path, request.method,
                    bool(request.cookies.get("pdb_session")),
                    resolve_auth_mode(DB_ENGINE),
                )
                # дублируем в STATUS_LOG с rid
                try:
                    from logger import log_status as _ls_401
                    _ls_401("warning", "auth",
                            f"401 {request.method} {path}",
                            request_id=_rid_401)
                except Exception:
                    pass
            except Exception:
                pass
            return JSONResponse(
                status_code=401,
                content={"detail": {"key": "error.unauthorized",
                                     "fallback": "Требуется авторизация"}})

    # 5. RBAC — проверка прав по таблице роутов
    try:
        from services.route_permissions import match_permission
        from config import ROLE_PERMISSIONS
        _u = getattr(request.state, "user", None)
        _perm = match_permission(request.method, path)
        # Stage 5.2 — fail-closed: route not registered in RBAC
        if _perm == "__deny__":
            return JSONResponse(
                status_code=403,
                content={"detail": {"key": "error.forbidden",
                                     "fallback":
                                     "Route not registered in RBAC"}})
        if _perm is not None and _u and not _u.get("local"):
            _role = _u.get("role")
            if _perm not in ROLE_PERMISSIONS.get(_role, frozenset()):
                return JSONResponse(
                    status_code=403,
                    content={"detail": {"key": "error.forbidden",
                                         "fallback": "Недостаточно прав"}})
    except Exception as _e:
        log.exception("RBAC middleware error: %s", _e)
        # fail-closed в team mode
        if resolve_auth_mode(DB_ENGINE) != "local":
            return JSONResponse(
                status_code=500,
                content={"detail": {"key": "error.rbacError",
                                     "fallback": "Внутренняя ошибка проверки прав"}})

    return await call_next(request)

from routers import system, projects, tags, images, ml
app.include_router(system.router)
app.include_router(projects.router)
app.include_router(tags.router)
app.include_router(images.router)
app.include_router(ml.router)
from routers import pipeline as _pipeline_router
app.include_router(_pipeline_router.router)
from routers import api_v2 as _api_v2_router
app.include_router(_api_v2_router.router)
from routers import webhooks as _webhooks_router
app.include_router(_webhooks_router.router)
# Team Edition: auth + setup routers.
from routers import auth as _auth_router
app.include_router(_auth_router.router)
from routers import setup as _setup_router
app.include_router(_setup_router.router)

# Storage router
from routers import storage as _storage_router
app.include_router(_storage_router.router)

# Backup router
from routers import backup as _backup_router
app.include_router(_backup_router.router)

# Batch router
from routers import autolabel_batch as _batch_router
app.include_router(_batch_router.router)

# Training router
from routers import train as _train_router
app.include_router(_train_router.router)
# use _read_run_metadata from routers/train.py
from routers.train import _read_run_metadata  # noqa: E402,F811

# Models router
from routers import models as _models_router
app.include_router(_models_router.router)

from routers import assignments as _assignments_router
app.include_router(_assignments_router.router)

# CSV-экспорт: stats.csv / files.csv / boxes.csv
from routers import exports_csv as _exports_csv_router
app.include_router(_exports_csv_router.router)

from routers import locks as _locks_router
app.include_router(_locks_router.router)

# Stage 3.11: new routers
from routers import settings as _settings_router
app.include_router(_settings_router.router)
from routers import videos as _videos_router
app.include_router(_videos_router.router)
from routers import tracks as _tracks_router
app.include_router(_tracks_router.router)

# V11.1.0: Раздача JS-модулей
_js_dir = os.path.join(BASE_DIR, "js")
if not os.path.exists(_js_dir):
    os.makedirs(_js_dir, exist_ok=True)

from starlette.staticfiles import StaticFiles as StarletteStaticFiles
class NoCacheStaticFiles(StarletteStaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

app.mount("/js", NoCacheStaticFiles(directory=_js_dir), name="js")

# Stage 5.4 — request_id + contextvar.
def _ensure_request_id(request: Request) -> str:
    """Идемпотентно устанавливает request.state.request_id и contextvar.

    Вызывается из любого middleware — если id уже установлен, повторно
    не генерируется (сохраняет корреляцию логов).
    """
    rid = getattr(request.state, "request_id", None)
    if not rid:
        rid = uuid.uuid4().hex[:8]
        request.state.request_id = rid
    try:
        from logger import set_request_id as _set_rid
        _set_rid(rid)
    except Exception:
        pass
    return rid


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    rid = _ensure_request_id(request)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response

@app.middleware("http")
async def _v2_api_key_guard(request: Request, call_next):
    """Bearer-токен для /api/v2/* если API_KEY задан."""
    path = request.url.path
    if path.startswith("/api/v2/"):
        # fail-closed: no API_KEY → 503
        try:
            from services.api_key import validate_api_key
            validate_api_key(request, required=True)
        except HTTPException as _he:
            return JSONResponse(status_code=_he.status_code,
                                content={"detail": _he.detail})
        # service user context for downstream audit
        request.state.user = {
            "id": 0, "username": "v2-api", "role": "admin",
            "local": False, "service": True,
        }
    return await call_next(request)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl:
        try:
            size = int(cl)
            path = request.url.path
            if path.endswith("/import") or "/import/" in path:
                limit = MAX_IMPORT_BYTES
            elif "/videos/upload" in path:
                limit = MAX_VIDEO_BYTES
            else:
                limit = MAX_UPLOAD_BYTES
            if size > limit:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Payload too large (max {limit // (1024*1024)} МБ)"}
                )
        except ValueError:
            pass
    return await call_next(request)

# V8.1.0: CSRF + CSP + X-Frame + nosniff
try:
    from security import SecurityMiddleware
    app.add_middleware(SecurityMiddleware)
except ImportError:
    log.warning("security.py не найден — CSRF/CSP отключены")

# Stage 5.3 — health-эндпоинт.
# Публичный (без авторизации), проверяет доступность БД.
@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    """[PATCH:STAGE4-F-08-health] Расширенный health-check.

    Возвращает статус БД, диска (>100MB free), ffmpeg, модели.
    Все проверки не поднимают исключений — деградация возвращает False.
    """
    from sqlalchemy import text as _health_text
    import shutil as _health_shutil
    import os as _health_os

    db_ok = False
    try:
        db.execute(_health_text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    disk_ok = False
    try:
        _free = _health_shutil.disk_usage(DATA_ROOT).free
        disk_ok = _free > 100 * 1024 * 1024
    except Exception:
        disk_ok = False

    ffmpeg_ok = False
    try:
        ffmpeg_ok = bool(_check_ffmpeg()[0])
    except Exception:
        ffmpeg_ok = False

    model_ok = False
    try:
        if _health_os.path.isdir(MODEL_DIR):
            for _f in _health_os.listdir(MODEL_DIR):
                if _f.endswith(".pt") or _f.endswith(".onnx"):
                    model_ok = True
                    break
    except Exception:
        model_ok = False

    # Stage 5.10 — disk_write + structured checks object.
    disk_write_ok = False
    try:
        _probe = _health_os.path.join(UPLOAD_DIR, ".health_probe")
        with open(_probe, "wb") as _f:
            _f.write(b"ok")
        _health_os.remove(_probe)
        disk_write_ok = True
    except Exception:
        disk_write_ok = False

    checks = {
        "db": db_ok,
        "disk_free": disk_ok,
        "disk_write": disk_write_ok,
        "ffmpeg": ffmpeg_ok,
        "model": model_ok,
    }
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "disk": disk_ok,
        "ffmpeg": ffmpeg_ok,
        "model": model_ok,
        "checks": checks,
        "version": APP_VERSION,
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    import traceback
    tb = traceback.format_exc()
    log.error("unhandled exception on %s %s:\n%s", request.method, request.url.path, tb)
    log_status("error", "system", f"{type(exc).__name__}: {exc}")
    if DEBUG_MODE:
        detail = f"{type(exc).__name__}: {exc}\n\n{tb}"
    else:
        req_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:8]
        detail = f"Внутренняя ошибка. Код для поддержки: {req_id}"
    return JSONResponse(status_code=500, content={"detail": detail})

# get_db moved to database.py

# ---------------------------------------------------------------------------
# Статика
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    if not os.path.exists(INDEX_HTML_PATH):
        raise HTTPException(500, "index.html не найден рядом с app.py")
    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    return (html.replace("__VERSION__", APP_VERSION)
                .replace("__AUTHOR__", AUTHOR))

@app.get("/style.css")
def get_style():
    if not os.path.exists(STYLE_CSS_PATH):
        raise HTTPException(404, "style.css не найден")
    return FileResponse(STYLE_CSS_PATH, media_type="text/css",
                        headers={"Cache-Control": "no-cache"})

# Stage 3.13: /app.js no longer referenced in index.html
# @app.get("/app.js")
def get_app_js():
    if not os.path.exists(APP_JS_PATH):
        raise HTTPException(404, "app.js не найден")
    return FileResponse(APP_JS_PATH, media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})

@app.get("/i18n.js")
def get_i18n_js():
    if not os.path.exists(I18N_JS_PATH):
        raise HTTPException(404, "i18n.js не найден")
    return FileResponse(I18N_JS_PATH, media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})

# ---------------------------------------------------------------------------
# Проекты
# ---------------------------------------------------------------------------

# ============================================================================
# V8.8.0: эндпоинты трекинга.
# ============================================================================

@app.get("/api/videos/{video_id}/track/status")
def video_track_status(video_id: int):
    return _track_snapshot()

@app.post("/api/videos/{video_id}/track/stop")
def video_track_stop(video_id: int):
    with TRACK_LOCK:
        if TRACK_STATE["status"] != "running":
            return {"status": "not_running"}
        TRACK_STATE["message"] = "Stopping..."
    TRACK_STOP.set()
    TRACK_EVENT.set()
    return {"status": "stopping"}

@app.get("/api/videos/{video_id}/track/events")
async def video_track_events(video_id: int):
    async def gen():
        snap = _track_snapshot()
        yield "data: " + json.dumps(snap, ensure_ascii=False) + "\n\n"
        last = json.dumps(snap, ensure_ascii=False)
        while True:
            await asyncio.get_event_loop().run_in_executor(
                None, TRACK_EVENT.wait, 1.0)
            TRACK_EVENT.clear()
            snap = _track_snapshot()
            payload = json.dumps(snap, ensure_ascii=False)
            if payload != last:
                yield "data: " + payload + "\n\n"
                last = payload
            if snap["status"] not in ("running",):
                break
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})

# ============================================================================
# V8.8.1: работа с треками — список, ручное связывание, навигация.
# ============================================================================

# _check_motion / _check_motion_batch перенесены в services/motion_service.py
# _check_motion_ex удалён.
# ============================================================================
# V10.5.0: умное копирование разметки и скелета из похожего кадра.
# ============================================================================

class SmartCopyIn(BaseModel):
    mode: str = "clone_all"
    # clone_all | fill_empty | replace_skeleton | replace_all

# Projects routes moved to routers/projects.py

# ---------------------------------------------------------------------------
# Object classes
# ---------------------------------------------------------------------------
# ML routes moved to routers/ml.py

# ---------------------------------------------------------------------------
# Логи
# ---------------------------------------------------------------------------
# Logs moved to routers/system.py

# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------
class ModelModeIn(BaseModel):
    use_single: bool = True

# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------
# moved → routers/models.py (@app.get("/api/models"))
# moved → routers/models.py (@app.get("/api/models/compatibility"))
# moved → routers/models.py (@app.post("/api/models/activate"))
# moved → routers/models.py (@app.delete("/api/models/{name}"))
# moved → routers/models.py (@app.post("/api/models/{name}/reveal"))

# moved → routers/models.py (@app.post("/api/models/{name}/rename"))
# moved → routers/models.py (@app.get("/api/models/bootstrap/status"))
# moved → routers/models.py (@app.get("/api/models/bootstrap/events"))
# moved → routers/models.py (@app.post("/api/models/download"))
# ============================================================================
# Экспорт активной/указанной модели в ONNX.
# ============================================================================
# moved → routers/models.py (@app.post("/api/models/{name}/export_onnx"))

# ---------------------------------------------------------------------------
# SAM
# ---------------------------------------------------------------------------
# SAM routes moved to routers/ml.py

# ---------------------------------------------------------------------------
# Active learning
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Training metrics
# ---------------------------------------------------------------------------
# moved → routers/train.py (@app.get("/api/train/runs"))
# moved → routers/train.py (@app.get("/api/train/runs/{folder}/metrics"))
# moved → routers/train.py (@app.get("/api/train/runs/{folder}/file/{name}"))
# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
# moved → routers/train.py (@app.post("/api/train/start"))
# moved → routers/train.py (@app.get("/api/train/status"))
# moved → routers/train.py (@app.post("/api/train/stop"))
# moved → routers/train.py (@app.get("/api/train/events"))
# moved → routers/train.py (@app.post("/api/train/reset"))
# ---------------------------------------------------------------------------
# Batch autolabel
# ---------------------------------------------------------------------------
# moved batch_autolabel_start
# moved batch_autolabel_status
# moved batch_autolabel_stop
# moved batch_autolabel_events
@app.get("/api/video/capabilities")
def video_capabilities():
    ok, err = _check_ffmpeg()
    return {
        "ffmpeg": ok, "error": err,
        "valid_extract_fps": list(VALID_EXTRACT_FPS),
        "default_extract_fps": DEFAULT_EXTRACT_FPS,
        "max_video_mb": MAX_VIDEO_MB,
        "max_frames": MAX_VIDEO_FRAMES,
    }

@app.get("/api/projects/{project_id}/videos")
def list_videos(project_id: int, db: Session = Depends(get_db)):
    rows = (db.query(Video)
              .filter(Video.project_id == project_id, Video.is_deleted.is_(False))
              .order_by(Video.id.desc()).all())
    counts = dict(
        db.query(ImageModel.video_id, func.count(ImageModel.id))
          .filter(ImageModel.video_id.isnot(None),
                  ImageModel.is_deleted.is_(False))
          .group_by(ImageModel.video_id).all()
    )
    return [{
        "id": v.id, "filename": v.filename, "fps": v.fps,
        "duration_sec": v.duration_sec, "extract_fps": v.extract_fps,
        "images_count": int(counts.get(v.id, 0)),
        "created_at": v.created_at.isoformat() if v.created_at else None,
    } for v in rows]

@app.get("/api/videos/{video_id}")
def get_video(video_id: int, db: Session = Depends(get_db)):
    v = db.query(Video).filter(Video.id == video_id).first()
    if not v or v.is_deleted:
        raise HTTPException(404, {"key": "error.videoNotFound", "fallback": "Video not found"})
    frames = (db.query(ImageModel.id, ImageModel.frame_index, ImageModel.filename)
                .filter(ImageModel.video_id == video_id,
                        ImageModel.is_deleted.is_(False))
                .order_by(ImageModel.frame_index).all())
    return {
        "id": v.id, "project_id": v.project_id, "filename": v.filename,
        "fps": v.fps, "duration_sec": v.duration_sec, "extract_fps": v.extract_fps,
        "images_count": len(frames),
        "frames": [{"id": fid, "index": idx, "filename": fn} for fid, idx, fn in frames],
    }

@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int, db: Session = Depends(get_db)):
    v = db.query(Video).filter(Video.id == video_id).first()
    if not v or v.is_deleted:
        raise HTTPException(404, {"key": "error.videoNotFound", "fallback": "Video not found"})
    v.is_deleted = True
    v.deleted_at = utcnow()
    now = utcnow()
    db.query(ImageModel).filter(
        ImageModel.video_id == video_id,
        ImageModel.is_deleted.is_(False),
    ).update({"is_deleted": True, "deleted_at": now}, synchronize_session=False)
    db.commit()
    # инвалидация кэшей
    try:
        _invalidate_phash_index(v.project_id)
        _invalidate_stats_cache(v.project_id)
    except Exception:
        pass
    log_status("warning", "video", f"Видео «{v.filename}» в корзине")
    return {"status": "ok", "video_id": video_id}

@app.post("/api/projects/{project_id}/videos/upload")
def upload_video(
    project_id: int,
    file: UploadFile = File(...),
    extract_fps: float = Form(DEFAULT_EXTRACT_FPS),
    db: Session = Depends(get_db),
):
    _rate_limit(_limiter_import, "video", "Слишком много загрузок видео. Подожди.")
    ok, err = _check_ffmpeg()
    if not ok:
        raise HTTPException(501, f"Видео недоступно: {err}. Установи ffmpeg.")
    proj = db.query(Project).filter(
        Project.id == project_id, Project.is_deleted.is_(False)).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    cl = file.headers.get("content-length")
    if cl:
        try:
            if int(cl) > MAX_VIDEO_BYTES:
                raise HTTPException(413, {"key": "error.fileTooLarge", "fallback": f"Видео больше {MAX_VIDEO_MB} МБ", "params": {"max_mb": MAX_VIDEO_MB}})
        except (ValueError, TypeError):
            pass
    fname = file.filename or "video.mp4"
    _, ext = _split_name_ext(fname)
    ext = (ext or "").lower()
    if ext not in VIDEO_EXTS:
        raise HTTPException(400, {"key": "error.unsupportedFormat", "fallback": f"Неподдерживаемый формат: {ext or '—'}"})
    try:
        efps = float(extract_fps)
    except (TypeError, ValueError):
        efps = DEFAULT_EXTRACT_FPS
    if efps not in VALID_EXTRACT_FPS:
        raise HTTPException(400, {"key": "error.invalidExtractFps", "fallback": f"extract_fps должен быть одним из: {VALID_EXTRACT_FPS}", "params": {"values": str(VALID_EXTRACT_FPS)}})
    video_uuid = uuid.uuid4().hex
    save_path = os.path.join(VIDEO_DIR, f"{video_uuid}{ext}")
    total = 0
    with open(save_path, "wb") as out:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_VIDEO_BYTES:
                _remove_file_safe(save_path)
                raise HTTPException(413, {"key": "error.fileTooLarge", "fallback": f"Видео больше {MAX_VIDEO_MB} МБ", "params": {"max_mb": MAX_VIDEO_MB}})
            out.write(chunk)
    if total < 1024:
        _remove_file_safe(save_path)
        raise HTTPException(400, "Файл слишком мал")
    info = _probe_video(save_path)
    if not info:
        _remove_file_safe(save_path)
        raise HTTPException(400, "ffprobe не смог прочитать видео")
    v = Video(
        project_id=project_id,
        filename=sanitize_display_name(fname, fallback="video" + ext),
        path=save_path,
        fps=info.get("fps") or None,
        frame_count=info.get("frame_count") or None,
        duration_sec=info.get("duration") or None,
        extract_fps=efps, images_count=0,
        created_at=utcnow(), is_deleted=False,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    frames_dir = os.path.join(VIDEO_DIR, f"{v.id}_frames")
    try:
        frame_paths = _extract_frames(save_path, frames_dir, efps, progress_cb=lambda pct: print(f'[ffmpeg] extracting: {pct*100:.1f}%'))
    except Exception as e:
        log.exception("extract failed for video %s", v.id)
        _remove_file_safe(save_path)
        v.is_deleted = True
        v.deleted_at = utcnow()
        db.commit()
        raise HTTPException(500, f"Ошибка извлечения кадров: {_safe_error_message(e)}")
    if not frame_paths:
        _remove_file_safe(save_path)
        v.is_deleted = True
        v.deleted_at = utcnow()
        db.commit()
        raise HTTPException(500, {"key": "error.noFramesExtracted", "fallback": "Не удалось извлечь ни одного кадра"})
    if len(frame_paths) > MAX_VIDEO_FRAMES:
        # V12.5.0: Удаляем лишние файлы с диска, чтобы не забивать мусором
        for fp in frame_paths[MAX_VIDEO_FRAMES:]:
            _remove_file_safe(fp)
        frame_paths = frame_paths[:MAX_VIDEO_FRAMES]
        log.warning("video %s: обрезано до %d кадров", v.id, MAX_VIDEO_FRAMES)
    used_names = {fn for (fn,) in db.query(ImageModel.filename)
                    .filter(ImageModel.project_id == project_id,
                            ImageModel.is_deleted.is_(False)).all()}
    stem, _ = _split_name_ext(v.filename)
    base_name = sanitize_display_name(stem, fallback="frame")
    first_image_id = None
    inserted = 0
    for idx, fp in enumerate(frame_paths):
        # Decompression bomb кадра
        # → кадр пропускается, сервер не падает с OOM.
        try:
            with open(fp, "rb") as _vf:
                _vdata = _vf.read()
            pil = _open_image_safe(_vdata).convert("RGB")
            _orig_w, _orig_h = pil.size
            pil = letterbox(pil, FIXED_SIZE, LETTERBOX_FILL)
            new_fname = f"{uuid.uuid4().hex}.jpg"
            new_path = os.path.join(UPLOAD_DIR, new_fname)
            pil.save(new_path, "JPEG", quality=85)
        except HTTPException:
            log.warning("video %s: frame %d rejected (decompression bomb?)", v.id, idx)
            continue
        except Exception:
            log.warning("video %s: frame %d unreadable", v.id, idx)
            continue
        try:
            ph = phash_hex(new_path)
        except Exception:
            ph = ""
        display_name = f"{base_name}_{idx:06d}.jpg"
        unique_name = _unique_name_mem(display_name, used_names)
        try:
            fsize = os.path.getsize(new_path)
        except OSError:
            fsize = 0
        # V8.3.0: таймкод кадра = idx / extract_fps
        ts_sec = (idx / efps) if efps > 0 else None
        # per-frame commit — previous frames survive errors
        try:
            im = ImageModel(
                project_id=project_id, filename=unique_name, path=new_path,
                width=FIXED_SIZE[0], height=FIXED_SIZE[1],
                is_deleted=False, phash=ph or None, is_hard=False,
                video_id=v.id, frame_index=idx,
                original_width=_orig_w, original_height=_orig_h,
                created_at=utcnow(), file_size=fsize,
                timestamp_sec=ts_sec,
            )
            db.add(im)
            db.flush()
            _queue_thumb(im.id, im.path)
            try:
                from services.auto_blur_service import schedule_auto_blur
                schedule_auto_blur(im.id, project_id)
            except Exception:
                pass
            if first_image_id is None:
                first_image_id = im.id
            db.commit()
            inserted += 1
        except Exception as e:
            log.warning('Frame %d failed: %s', idx, e)
            db.rollback()
            _remove_file_safe(fp)
            continue
        _remove_file_safe(fp)
    v.images_count = inserted
    _db_commit_safe(db)
    _invalidate_stats_cache(project_id)
    try:
        shutil.rmtree(frames_dir, ignore_errors=True)
    except Exception:
        pass
    log_status("success", "video",
               f"Видео «{v.filename}» → {inserted} кадров @ {efps}fps")
    return {
        "video_id": v.id, "filename": v.filename, "fps": v.fps,
        "duration_sec": v.duration_sec, "extract_fps": v.extract_fps,
        "images_count": inserted, "first_image_id": first_image_id,
    }

# ---------------------------------------------------------------------------
# Похожие / копирование
# ---------------------------------------------------------------------------
@app.get("/api/projects/{project_id}/similar/{image_id}")
def similar_images(project_id: int, image_id: int,
                   threshold: int = SIMILAR_DEFAULT_THRESHOLD,
                   limit: int = 30, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id,
                                       ImageModel.project_id == project_id).first()
    if not img or not img.phash:
        return {"items": [], "threshold": threshold}
    target = img.phash
    target_int = _hex_to_int(target)
    prefix = target[:1]
    rows = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False),
                      ImageModel.id != image_id,
                      ImageModel.phash.isnot(None),
                      ImageModel.phash.like(f"{prefix}%"))
              .all())
    items = []
    for r in rows:
        d = _hamming_int(target_int, _hex_to_int(r.phash))
        if d <= threshold:
            items.append({"id": r.id, "filename": r.filename, "distance": d})
    if len(items) < limit:
        _rest_q = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
                     .filter(ImageModel.project_id == project_id,
                             ImageModel.is_deleted.is_(False),
                             ImageModel.id != image_id,
                             ImageModel.phash.isnot(None),
                             ~ImageModel.phash.like(f"{prefix}%"))
                     .limit(5000)
                     .yield_per(500))
        for r in _rest_q:
            d = _hamming_int(target_int, _hex_to_int(r.phash))
            if d <= threshold:
                items.append({"id": r.id, "filename": r.filename, "distance": d})
    items.sort(key=lambda x: x["distance"])
    items = items[:limit]
    ids = [it["id"] for it in items]
    if ids:
        counts = dict(db.query(Annotation.image_id, func.count(Annotation.id))
                        .filter(Annotation.image_id.in_(ids))
                        .group_by(Annotation.image_id).all())
        for it in items:
            it["annotation_count"] = int(counts.get(it["id"], 0))
    else:
        for it in items:
            it["annotation_count"] = 0
    return {"items": items, "threshold": threshold}

@app.post("/api/images/{target_id}/copy_annotations_from/{source_id}")
def copy_annotations(target_id: int, source_id: int, db: Session = Depends(get_db)):
    """Копирует рамки + behavior + animal_id с source на target.

    [PATCH:F-12] ВАЖНО: НЕ копирует keypoints/скелеты.
    Для скелетов используйте /api/images/{target}/smart_copy_from/{source}
    с mode=clone_all.
    """
    target = db.query(ImageModel).filter(ImageModel.id == target_id).first()
    source = db.query(ImageModel).filter(ImageModel.id == source_id).first()
    if not target or not source:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    if target.project_id != source.project_id:
        raise HTTPException(400, "Изображения из разных проектов")
    src_anns = db.query(Annotation).filter(Annotation.image_id == source_id).all()
    # V10.4.1: сначала чистим keypoints target-а (иначе orphan + FK-конфликт),
    # потом аннотации; behavior и animal_id сохраняем (это смысл "скопировать
    # разметку с похожего кадра").
    _old_target_ids = [row.id for row in db.query(Annotation.id)
                                            .filter(Annotation.image_id == target_id).all()]
    if _old_target_ids:
        db.query(Keypoint).filter(Keypoint.annotation_id.in_(_old_target_ids)) \
            .delete(synchronize_session=False)
    db.query(Annotation).filter(Annotation.image_id == target_id).delete()
    for a in src_anns:
        db.add(Annotation(image_id=target_id, x=a.x, y=a.y, w=a.w, h=a.h,
                          label=a.label, confidence=None, is_frozen=False,
                          behavior=a.behavior, animal_id=a.animal_id))
    db.commit()
    return {"status": "ok", "count": len(src_anns)}

# ============================================================================
# V8.6.9: копирование скелета между похожими кадрами.
# ============================================================================

@app.get("/api/images/{image_id}/similar_with_skeleton")
def similar_with_skeleton(image_id: int,
                           threshold: int = SIMILAR_DEFAULT_THRESHOLD,
                           limit: int = 20,
                           db: Session = Depends(get_db)):
    """V8.6.9: похожие кадры, у которых есть хотя бы один размеченный скелет."""
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img or not img.phash:
        return {"items": [], "threshold": threshold, "reason": "no_phash"}
    target_int = _hex_to_int(img.phash)
    prefix = img.phash[:1]
    rows = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
              .filter(ImageModel.project_id == img.project_id,
                      ImageModel.is_deleted.is_(False),
                      ImageModel.id != image_id,
                      ImageModel.phash.isnot(None),
                      ImageModel.phash.like(f"{prefix}%"))
              .all())
    if len(rows) < limit:
        rest = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
                  .filter(ImageModel.project_id == img.project_id,
                          ImageModel.is_deleted.is_(False),
                          ImageModel.id != image_id,
                          ImageModel.phash.isnot(None),
                          ~ImageModel.phash.like(f"{prefix}%"))
                  .limit(5000).all())
        rows = list(rows) + list(rest)
    # Считаем distance, фильтруем по threshold
    cand = []
    for r in rows:
        d = _hamming_int(target_int, _hex_to_int(r.phash))
        if d <= threshold:
            cand.append((r, d))
    if not cand:
        return {"items": [], "threshold": threshold, "reason": "no_similar"}
    # Оставляем только те, где есть хоть один keypoint
    img_ids = [r.id for r, _ in cand]
    kp_ann_ids = [row.annotation_id for row in
                  db.query(Keypoint.annotation_id)
                    .join(Annotation, Annotation.id == Keypoint.annotation_id)
                    .filter(Annotation.image_id.in_(img_ids))
                    .distinct().all()]
    if not kp_ann_ids:
        return {"items": [], "threshold": threshold, "reason": "no_skeletons"}
    ann_to_img = dict(
        db.query(Annotation.id, Annotation.image_id)
          .filter(Annotation.id.in_(kp_ann_ids)).all()
    )
    img_to_kp_count = defaultdict(int)
    for aid in kp_ann_ids:
        iid = ann_to_img.get(aid)
        if iid:
            img_to_kp_count[iid] += 1
    items = []
    for r, d in cand:
        n = img_to_kp_count.get(r.id, 0)
        if n == 0:
            continue
        items.append({
            "id": r.id, "filename": r.filename,
            "distance": d, "skeleton_count": n,
        })
    items.sort(key=lambda x: (x["distance"], -x["skeleton_count"]))
    return {"items": items[:limit], "threshold": threshold}

# Images (base CRUD) moved to routers/images.py


class PredictBehaviorIn(BaseModel):
    """V10.5.5: точки + опционально animal_id для motion."""
    keypoints: list[dict] = Field(default_factory=list)
    animal_id: Optional[int] = None

@app.post("/api/images/{image_id}/predict_behavior")
def predict_behavior(image_id: int,
                      payload: PredictBehaviorIn = Body(default_factory=PredictBehaviorIn),
                      db: Session = Depends(get_db)):
    """V8.8.2: определить поведение по скелету + движению."""
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound",
                                 "fallback": "Image not found"})
    kps = payload.keypoints or []
    motion = None
    if payload.animal_id is not None:
        motion = _check_motion(db, image_id, payload.animal_id)
    if not kps and not motion:
        return {"behavior": None, "confidence": 0.0,
                "reason": "no_keypoints_supplied"}
    _bbox = getattr(payload, "bbox", None)
    result = predict_behavior_from_keypoints(kps, motion=motion, bbox=_bbox, project_id=img.project_id)
    result["received_points"] = len(kps)
    result["visible_names"] = sorted([
        str(p.get("name", "")) for p in kps
        if float(p.get("visibility", 1.0)) >= 0.5
    ])
    return result

# Autolabel routes moved to routers/ml.py

# ---------------------------------------------------------------------------
# Debug-авторазметка (V7.8.0)
# ---------------------------------------------------------------------------
@app.post("/api/images/{image_id}/autolabel_debug")
def autolabel_debug(
    image_id: int,
    payload: AutolabelIn = Body(default_factory=AutolabelIn),
    db: Session = Depends(get_db),
):
    """
    Прогоняет YOLO без фильтра по классам, возвращает все детекции с именем класса.
    Клиент сам решает: отрисовать всё, сохранить только target-класс.
    На сервере ничего не сохраняется.
    """
    _rate_limit(_limiter_autolabel, "local", "Слишком много авторазметок.")

    model_path = get_active_model_path(db)
    if not model_path:
        raise HTTPException(501, {"key": "error.noModel", "fallback": "Активная модель не найдена"})
    try:
        model = _get_yolo_model(model_path)
    except ImportError:
        raise HTTPException(501, {"key": "error.noUltralytics", "fallback": "ultralytics не установлен"})
    except Exception as e:
        raise HTTPException(500, f"Ошибка загрузки модели: {_safe_error_message(e)}")

    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    project = db.query(Project).filter(Project.id == img.project_id).first()
    if not project:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})

    target_label = project.object_class or DEFAULT_OBJECT_CLASS
    target_ids = _resolve_target_class_ids(model, target_label)

    W = img.width or 640
    H = img.height or 640
    try:
        results = model(img.path, conf=CONF_THRESHOLD, verbose=False)
    except Exception as e:
        log.exception("autolabel_debug: model predict failed")
        raise HTTPException(500, f"Модель не смогла обработать: {_safe_error_message(e)}")

    names = getattr(model, "names", {}) or {}
    detections = []
    target_detections = []

    for r in results:
        for box in r.boxes:
            try:
                cls_id = int(box.cls[0])
            except Exception:
                cls_id = 0
            cls_name = str(names.get(cls_id, f"class_{cls_id}")).strip() or f"class_{cls_id}"
            try:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
            except Exception:
                continue
            try:
                bconf = float(box.conf[0])
            except Exception:
                bconf = None

            det = {
                "x": max(0.0, min(1.0, x1 / W)),
                "y": max(0.0, min(1.0, y1 / H)),
                "w": max(0.0, min(1.0, (x2 - x1) / W)),
                "h": max(0.0, min(1.0, (y2 - y1) / H)),
                "label": cls_name,
                "confidence": bconf,
                "class_id": cls_id,
                "is_target": bool(target_ids) and (cls_id in target_ids),
            }
            detections.append(det)
            if det["is_target"]:
                target_detections.append({
                    "x": det["x"], "y": det["y"], "w": det["w"], "h": det["h"],
                    "label": target_label,
                    "confidence": bconf,
                })

    try:
        target_dedup = dedup_boxes(target_detections)
    except Exception as e:
        log.error('dedup_boxes failed: %s', e)
        target_dedup = target_detections
    detections.sort(key=lambda d: (d.get("confidence") or 0.0), reverse=True)

    # V8.2.1: сервер сам сохраняет — клиент больше НЕ POST'ит
    # (иначе existing теряли confidence/label/frozen).
    mode = _norm_mode(payload.mode)
    existing_full = _load_annotations(db, img.id)
    existing_xywh = [{"x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"]}
                     for e in existing_full]
    if mode == "add":
        unique_new = []
        skipped = 0
        for d in target_dedup:
            if any(_is_duplicate_box(d, e) for e in existing_xywh):
                skipped += 1
            else:
                unique_new.append(d)
        if unique_new:
            db.add_all([
                Annotation(image_id=img.id, x=a["x"], y=a["y"],
                           w=a["w"], h=a["h"], label=target_label,
                           confidence=a["confidence"], is_frozen=False,
                           behavior=None, animal_id=None)
                for a in unique_new
            ])
            db.commit()
        added = len(unique_new)
    else:
        db.query(Annotation).filter(
            Annotation.image_id == img.id
        ).delete(synchronize_session=False)
        db.add_all([
            Annotation(image_id=img.id, x=a["x"], y=a["y"],
                       w=a["w"], h=a["h"], label=target_label,
                       confidence=a["confidence"], is_frozen=False,
                       behavior=None, animal_id=None)
            for a in target_dedup
        ])
        db.commit()
        added = len(target_dedup)
        skipped = 0

    log.info("[autolabel_debug] image=%s mode=%s existing=%d new=%d skipped=%d",
             img.id, mode, len(existing_full), added, skipped)

    return {
        "target_class": target_label,
        "detections": detections,
        "total": len(detections),
        "target_count": len(target_dedup),
        "saved_boxes": _load_annotations(db, img.id),
        "added": added,
        "skipped": skipped,
        "mode": mode,
    }

# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------
@app.post("/api/images/bulk_rename")
def bulk_rename(payload: BulkRenameIn, db: Session = Depends(get_db)):
    ids = payload.image_ids or []
    if not ids:
        raise HTTPException(400, {"key": "error.emptyImageIds", "fallback": "Пустой список image_ids"})
    if len(ids) > 5000:
        raise HTTPException(400, "Максимум 5000 за раз")
    pattern = (payload.pattern or "").strip()
    if "{n" not in pattern:
        raise HTTPException(400, "Паттерн должен содержать {n} или {n:04d}")
    if len(pattern) > 200:
        raise HTTPException(400, "Слишком длинный паттерн")
    imgs = db.query(ImageModel).filter(ImageModel.id.in_(ids)).all()
    if not imgs:
        raise HTTPException(404, "Изображения не найдены")
    project_ids = {im.project_id for im in imgs}
    if len(project_ids) > 1:
        raise HTTPException(400, "Изображения из разных проектов")
    pid = project_ids.pop()
    existing_names = {fn for (fn,) in db.query(ImageModel.filename)
                        .filter(ImageModel.project_id == pid,
                                ImageModel.id.notin_(ids)).all()}
    pending_names = set()
    renamed = 0
    failed = []
    order = sorted(imgs, key=lambda im: im.id)
    n = int(payload.start)
    for im in order:
        try:
            name = pattern.format(n=n)
        except (KeyError, ValueError):
            failed.append({"id": im.id, "reason": "Некорректный паттерн"})
            n += 1
            continue
        name = re.sub(r'[\\/:*?"<>|]', '_', name).strip().rstrip('.')
        if not name:
            failed.append({"id": im.id, "reason": "Пустое имя"})
            n += 1
            continue
        _, ext = _split_name_ext(im.filename)
        stem, _ = _split_name_ext(name)
        final = stem + (ext or "")
        if final in existing_names or final in pending_names:
            base, ext2 = _split_name_ext(final)
            k = 1
            while f"{base} ({k}){ext2}" in existing_names or f"{base} ({k}){ext2}" in pending_names:
                k += 1
            final = f"{base} ({k}){ext2}"
        pending_names.add(final)
        im.filename = final
        renamed += 1
        n += 1
    db.commit()
    log_status("info", "project", f"Bulk rename: {renamed} файлов в проекте #{pid}")
    return {"renamed": renamed, "failed": failed[:20], "failed_count": len(failed)}
# moved bulk_move
# moved bulk_copy
@app.get("/api/projects/{project_id}/duplicates")
def project_duplicates(project_id: int, threshold: int = PHASH_DUPLICATE_THRESHOLD,
                        db: Session = Depends(get_db)):
    index, hashes_map = _get_phash_index(db, project_id)
    if len(hashes_map) < 2:
        return {"groups": [], "total": 0}

    parent = {iid: iid for iid in hashes_map}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for iid, h_int in hashes_map.items():
        dups = _find_duplicates_via_index(h_int, index, hashes_map, exclude_id=iid, max_dist=threshold)
        for dup_id, _ in dups:
            union(iid, dup_id)

    groups_map = defaultdict(list)
    for iid in hashes_map:
        groups_map[find(iid)].append(iid)

    # Подтягиваем метаданные только для найденных дубликатов
    all_dup_ids = set()
    for ids in groups_map.values():
        if len(ids) >= 2:
            all_dup_ids.update(ids)

    if not all_dup_ids:
        return {"groups": [], "total": 0}

    meta_rows = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash,
                          ImageModel.file_size, ImageModel.width, ImageModel.height)
                   .filter(ImageModel.id.in_(all_dup_ids)).all())
    meta_map = {r.id: r for r in meta_rows}

    out = []
    for root_id, ids in groups_map.items():
        if len(ids) < 2: continue
        items = [meta_map[iid] for iid in ids if iid in meta_map]
        items_sorted = sorted(items, key=lambda x: (x.file_size or 0), reverse=True)
        out.append({
            "representative_id": items_sorted[0].id,
            "items": [{
                "id": it.id, "filename": it.filename,
                "file_size": it.file_size, "width": it.width,
                "height": it.height, "phash": it.phash,
            } for it in items_sorted],
        })
    out.sort(key=lambda g: len(g["items"]), reverse=True)
    return {"groups": out[:100], "total": len(out)}

# ---------------------------------------------------------------------------
# Импорт датасета
# ---------------------------------------------------------------------------
# V10.4.1: кооперативная отмена импорта zip. Клиент ставит флаг через
# POST /api/import/cancel; _process_dataset_zip проверяет его в hot-loop
# и завершается с HTTPException(499).
IMPORT_CANCELS = {}  # V12.5.0: {project_id: threading.Event()}
# local _process_dataset_zip removed (source of truth: services/zip_import_service.py)


# IMPORT_PROGRESS lives in services/zip_import_service.py



@app.get("/api/import/status")
def get_import_status(project_id: int):
    return IMPORT_PROGRESS.get(project_id, {"stage": "idle"})


@app.post("/api/import/cancel")
def import_cancel():
    """V10.4.1: кооперативная отмена активного импорта.

    Ставит флаг IMPORT_CANCEL. _process_dataset_zip проверяет его
    в hot-loop и завершается с 499. Ранее загруженные файлы остаются
    в проекте (частичный импорт).
    """
    for ev in IMPORT_CANCELS.values():
        ev.set()
    log_status("warning", "import", "Запрошена отмена импорта")
    return {"status": "cancelling"}

@app.post("/api/projects/{project_id}/import")
def import_annotations(project_id: int, file: UploadFile = File(...),
                       user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    # V12.5.0: Создаем изолированный флаг отмены для этого проекта
    cancel_event = threading.Event()
    IMPORT_CANCELS[project_id] = cancel_event
    _rate_limit(_limiter_import, "local", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
    proj = db.query(Project).filter(Project.id == project_id,
                                     Project.is_deleted.is_(False)).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    content_length = file.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_IMPORT_BYTES:
                raise HTTPException(413, f"Архив больше {MAX_IMPORT_MB} МБ")
        except (ValueError, TypeError):
            pass
    tmp_zip = os.path.join(IMPORT_DIR, f"_upload_{uuid.uuid4().hex}.zip")
    try:
        total = 0
        with open(tmp_zip, "wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_IMPORT_BYTES:
                    raise HTTPException(413, f"Архив больше {MAX_IMPORT_MB} МБ")
                out.write(chunk)
        # Smart import: detect full DatasetBuilder backup and delegate.
        is_full_backup = False
        try:
            with zipfile.ZipFile(tmp_zip) as _zf_smart:
                if "manifest.json" in _zf_smart.namelist():
                    with _zf_smart.open("manifest.json") as _mf_smart:
                        _manifest_smart = json.loads(
                            _mf_smart.read().decode("utf-8"))
                        if _manifest_smart.get("format") == "datasetbuilder_full_backup":
                            is_full_backup = True
        except Exception:
            pass

        if is_full_backup:
            from services.backup_service import import_full_project
            try:
                _res_smart = import_full_project(db, tmp_zip)
                _proj_smart = (
                    db.query(Project)
                      .filter(Project.id == _res_smart["project_id"])
                      .first()
                )
                return {
                    "status": "ok",
                    "is_full_backup": True,
                    "project_id": _res_smart["project_id"],
                    "project_name": (
                        _proj_smart.name if _proj_smart else "Imported Project"
                    ),
                }
            except Exception as _e_smart:
                log.exception("Smart import full backup failed")
                raise HTTPException(
                    500,
                    f"\u041e\u0448\u0438\u0431\u043a\u0430 "
                    f"\u0432\u043e\u0441\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f: "
                    f"{_safe_error_message(_e_smart)}",
                )

        return _process_dataset_zip(tmp_zip, project_id, db, cancel_event)
    finally:
        # prevent IMPORT_CANCELS memory leak
        IMPORT_CANCELS.pop(project_id, None)
        _remove_file_safe(tmp_zip)

# ---------------------------------------------------------------------------
# External importers
# ---------------------------------------------------------------------------
# moved _download_to_file
@contextmanager
def _external_import_tmp(prefix: str):
    """Временный zip для внешнего импорта. Убирается автоматически."""
    tmp = os.path.join(IMPORT_DIR, f"_{prefix}_{uuid.uuid4().hex}.zip")
    try:
        yield tmp
    finally:
        _remove_file_safe(tmp)

def _finalize_external_import(tmp_zip: str, project_id: int, db,
                              source_name: str = "источник",
                              cancel_event=None):
    """Проверяет, что скачался валидный zip, и передаёт его в _process_dataset_zip."""
    if not os.path.exists(tmp_zip) or os.path.getsize(tmp_zip) < 100:
        raise HTTPException(400, f"Пустой ответ от {source_name}")
    with open(tmp_zip, "rb") as f:
        if f.read(2) != b"PK":
            raise HTTPException(400, f"{source_name} вернул не zip")
    return _process_dataset_zip(
        tmp_zip, project_id, db,
        cancel_event=cancel_event,
        source=(source_name or "external").lower().replace(" ", "_"),
    )

@app.post("/api/projects/{project_id}/import/roboflow")
def import_roboflow(project_id: int, payload: ImportRoboflowIn,
                     user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    cancel_event = threading.Event()
    IMPORT_CANCELS[project_id] = cancel_event
    _rate_limit(_limiter_import, "roboflow", "Слишком много импортов. Подожди.")
    if not payload.api_key or not payload.workspace or not payload.project:
        raise HTTPException(400, "api_key, workspace, project обязательны")
    url = (f"https://api.roboflow.com/{payload.workspace}/{payload.project}/"
           f"{payload.version}/coco?api_key={payload.api_key}")
    with _external_import_tmp("roboflow") as tmp_zip:
        try:
            _download_to_file(url, tmp_zip)
            return _finalize_external_import(tmp_zip, project_id, db, "Roboflow", cancel_event=cancel_event)
        except HTTPException:
            raise
        except Exception as e:
            log.exception("roboflow import failed")
            raise HTTPException(500, f"Roboflow: {_safe_error_message(e)}")

@app.post("/api/projects/{project_id}/import/supervisely")
def import_supervisely(project_id: int, payload: ImportSuperviselyIn,
                        user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    cancel_event = threading.Event()
    IMPORT_CANCELS[project_id] = cancel_event
    _rate_limit(_limiter_import, "supervisely", "Слишком много импортов. Подожди.")
    if not payload.api_token:
        raise HTTPException(400, "api_token обязателен")
    base = "https://app.supervisely.com"
    headers = {"x-api-key": payload.api_token}
    def _api_get(path):
        req = urllib.request.Request(base + path, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    # V7.9.3: единый context manager вместо ручного try/finally.
    with _external_import_tmp("sv") as tmp_zip:
        try:
            try:
                ds = _api_get(f"/api/project/{payload.project_id}/datasets")
            except Exception as e:
                raise HTTPException(400, f"Supervisely API: {_safe_error_message(e)}")
            datasets = ds if isinstance(ds, list) else (ds.get("datasets") or [])
            if not datasets:
                raise HTTPException(404, "В проекте нет датасетов")
            target_ds = None
            if payload.dataset_id:
                target_ds = next((d for d in datasets if d.get("id") == payload.dataset_id), None)
            if target_ds is None:
                target_ds = datasets[0]
            ds_id = target_ds["id"]
            try:
                r = _api_get(f"/api/dataset.download/{ds_id}/coco")
            except Exception as e:
                raise HTTPException(500, f"Supervisely download: {_safe_error_message(e)}")
            if isinstance(r, dict) and r.get("url"):
                _download_to_file(r["url"], tmp_zip, extra_headers=headers)
            else:
                raise HTTPException(500, "Supervisely не вернул ссылку на архив")
            return _finalize_external_import(tmp_zip, project_id, db, "Supervisely", cancel_event=cancel_event)
        except HTTPException:
            raise
        except Exception as e:
            log.exception("supervisely import failed")
            raise HTTPException(500, f"Supervisely: {_safe_error_message(e)}")

@app.post("/api/projects/{project_id}/import/url")
def import_url(project_id: int, payload: ImportUrlIn,
                user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    _rate_limit(_limiter_import, "url", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
    cancel_event = threading.Event()
    IMPORT_CANCELS[project_id] = cancel_event
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(400, "URL обязателен")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(400, "URL должен начинаться с http(s)://")
    if not is_safe_external_url(url):
        raise HTTPException(400, "URL ведёт во внутреннюю сеть (SSRF protection)")
    with _external_import_tmp("url") as tmp_file:
        try:
            _download_to_file(url, tmp_file)
            if not os.path.exists(tmp_file) or os.path.getsize(tmp_file) < 100:
                raise HTTPException(400, "Пустой ответ")
            with open(tmp_file, "rb") as f:
                head = f.read(4)
            if head[:2] == b"PK":
                return _process_dataset_zip(tmp_file, project_id, db,
                                            cancel_event=cancel_event,
                                            source="url")
            with open(tmp_file, "rb") as f:
                h64 = f.read(64)
            fmt = _detect_image_format(h64)
            if fmt:
                with _external_import_tmp("url_single") as single_zip:
                    with zipfile.ZipFile(single_zip, "w") as z:
                        fname = payload.filename or os.path.basename(url.split("?", 1)[0]) or "image"
                        z.write(tmp_file, fname)
                    return _process_dataset_zip(single_zip, project_id, db,
                                                cancel_event=cancel_event,
                                                source="url")
            raise HTTPException(400, "Ссылка не ведёт на zip или картинку")
        except HTTPException:
            raise
        except Exception as e:
            log.exception("url import failed")
            raise HTTPException(500, f"URL: {_safe_error_message(e)}")

@app.post("/api/projects/{project_id}/import/local_folder")
def import_local_folder(project_id: int, payload: ImportLocalFolderIn,
                         user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    _rate_limit(_limiter_import, "local_folder", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
    # cancel_event был undefined
    cancel_event = threading.Event()
    IMPORT_CANCELS[project_id] = cancel_event
    src = (payload.path or "").strip()
    if not src:
        raise HTTPException(400, "Путь обязателен")
    if not os.path.isabs(src):
        raise HTTPException(400, "Путь должен быть абсолютным")
    if not os.path.isdir(src):
        raise HTTPException(404, f"Папка не найдена: {src}")
    _allowed_roots = [
        os.path.realpath(IMPORT_DIR),
        os.path.realpath(UPLOAD_DIR),
    ]
    try:
        from services.settings_service import get_setting as _gs
        _custom_root = _gs(db, "import_root", "")
        if _custom_root:
            _real = os.path.realpath(_custom_root)
            _forbidden = {
                os.path.realpath(p) for p in ("/", "C:\\", "C:/", "/etc",
                                              "/proc", "/sys", "/dev")
            }
            if _real in _forbidden:
                raise HTTPException(403, "import_root не может указывать на системный корень")
            _data_real = os.path.realpath(DATA_ROOT)
            if not (_real == _data_real or _real.startswith(_data_real + os.sep)):
                raise HTTPException(403, "import_root должен быть подкаталогом DATA_ROOT")
            _allowed_roots.append(_real)
    except HTTPException:
        raise
    except Exception:
        pass
    _src_real = os.path.realpath(src)
    if not any(_src_real == r or _src_real.startswith(r + os.sep)
               for r in _allowed_roots):
        raise HTTPException(403, "Папка вне разрешённых import-каталогов (см. настройку import_root)")
    imgs = []
    # skip symlinks & enforce containment
    _src_real_for_imgs = os.path.realpath(src)
    def _safe_collect(p):
        try:
            if os.path.islink(p):
                return False
            real = os.path.realpath(p)
            if not (real == _src_real_for_imgs
                    or real.startswith(_src_real_for_imgs + os.sep)):
                return False
            return True
        except OSError:
            return False
    if payload.recursive:
        for root, _dirs, files in os.walk(src, followlinks=False):
            for f in files:
                full = os.path.join(root, f)
                if _is_image_ext(f) and _safe_collect(full):
                    imgs.append(full)
    else:
        for f in os.listdir(src):
            full = os.path.join(src, f)
            if _is_image_ext(f) and _safe_collect(full):
                imgs.append(full)
    if not imgs:
        raise HTTPException(400, "В папке нет изображений")
    # V7.9.3: единый context manager.
    with _external_import_tmp("localfolder") as tmp_zip:
        try:
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_STORED) as z:
                for p in imgs:
                    try:
                        z.write(p, arcname=os.path.basename(p))
                    except OSError:
                        continue
            return _process_dataset_zip(tmp_zip, project_id, db, cancel_event, source="local_folder")
        except HTTPException:
            raise
        except Exception as e:
            log.exception("local folder import failed")
            raise HTTPException(500, f"Папка: {_safe_error_message(e)}")
# moved _http_get_json

@app.post("/api/projects/{project_id}/import/labelbox")
def import_labelbox(project_id: int, payload: ImportLabelboxIn,
                     user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    _rate_limit(_limiter_import, "labelbox", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
    # cancel_event был undefined
    cancel_event = threading.Event()
    IMPORT_CANCELS[project_id] = cancel_event
    if not payload.api_key or not payload.project_id:
        raise HTTPException(400, "api_key и project_id обязательны")
    headers = {"Authorization": f"Bearer {payload.api_key}", "Accept": "application/json"}
    gql_url = "https://api.labelbox.com/graphql"
    query = """
    mutation ExportProject($projectId: ID!) {
      exportProject(
        where: { id: $projectId }
        options: { exportParams: { includeAttachments: false, includeMetadata: false } }
      ) { jobId state createdAt }
    }
    """
    try:
        r = _http_post_json(gql_url, headers, {"query": query, "variables": {"projectId": payload.project_id}})
    except Exception as e:
        raise HTTPException(500, f"Labelbox API: {_safe_error_message(e)}")
    if "errors" in r:
        raise HTTPException(400, f"Labelbox: {r['errors'][0].get('message', 'unknown error')}")
    job = ((r.get("data") or {}).get("exportProject") or {})
    job_id = job.get("jobId")
    if not job_id:
        raise HTTPException(500, "Labelbox не вернул jobId")
    status_query = """
    query ExportStatus($jobId: ID!) {
      projectExport(id: $jobId) { state downloadUrl createdAt }
    }
    """
    download_url = None
    for _ in range(120):
        time.sleep(5)
        try:
            s = _http_post_json(gql_url, headers, {"query": status_query, "variables": {"jobId": job_id}})
        except Exception:
            continue
        pe = ((s.get("data") or {}).get("projectExport") or {})
        state = (pe.get("state") or "").lower()
        if state in ("completed", "done", "success"):
            download_url = pe.get("downloadUrl")
            break
        if state in ("failed", "error"):
            raise HTTPException(500, f"Labelbox export {state}")
    if not download_url:
        raise HTTPException(504, "Labelbox: экспорт не завершён за 10 минут")
    tmp_json = os.path.join(IMPORT_DIR, f"_labelbox_{uuid.uuid4().hex}.json")
    try:
        _download_to_file(download_url, tmp_json)
        with open(tmp_json, "r", encoding="utf-8") as f:
            content = f.read()
        items = []
        try:
            parsed = json.loads(content)
            items = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        if not items:
            raise HTTPException(400, "Labelbox: пустой экспорт")
        coco = _labelbox_to_coco(items, payload.project_id)
        if not coco["images"]:
            raise HTTPException(400, "Labelbox: нет изображений в экспорте")
        image_urls = {}
        for item in items:
            dr = item.get("data_row") or {}
            gkey = dr.get("global_key") or dr.get("external_id") or ""
            rd = dr.get("row_data") or ""
            if gkey and isinstance(rd, str) and rd.startswith("http"):
                image_urls[gkey] = rd
        tmp_zip = os.path.join(IMPORT_DIR, f"_labelbox_{uuid.uuid4().hex}.zip")
        try:
            _coco_to_zip(coco, image_urls, tmp_zip)
            return _process_dataset_zip(tmp_zip, project_id, db, cancel_event, source="labelbox")
        finally:
            _remove_file_safe(tmp_zip)
    finally:
        _remove_file_safe(tmp_json)

@app.post("/api/projects/{project_id}/import/scale")
def import_scale(project_id: int, payload: ImportScaleIn,
                  user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    cancel_event = threading.Event()
    IMPORT_CANCELS[project_id] = cancel_event
    _rate_limit(_limiter_import, "scale", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
    if not payload.api_key or not payload.dataset_id:
        raise HTTPException(400, "api_key и dataset_id обязательны")
    auth = base64.b64encode(f"{payload.api_key}:".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    url = f"https://api.scale.com/v1/nucleus/dataset/{payload.dataset_id}/exportForTraining"
    try:
        r = _http_get_json(url, headers, timeout=600)
    except urllib.error.HTTPError as he:
        raise HTTPException(he.code, f"Scale API: {he.reason}")
    except Exception as e:
        raise HTTPException(500, f"Scale API: {_safe_error_message(e)}")
    items = r if isinstance(r, list) else (r.get("items") or r.get("dataset_items") or [])
    if not items:
        raise HTTPException(400, "Scale: пустой экспорт")
    coco = _scale_to_coco(items)
    if not coco["images"]:
        raise HTTPException(400, "Scale: нет изображений в экспорте")
    image_urls = {}
    for it in items:
        ref = it.get("reference_id") or it.get("external_id") or it.get("id") or ""
        u = it.get("image_url") or it.get("url") or it.get("original_url") or ""
        if ref and u:
            image_urls[ref] = u
    # V7.9.3: единый context manager.
    with _external_import_tmp("scale") as tmp_zip:
        _coco_to_zip(coco, image_urls, tmp_zip)
        return _finalize_external_import(tmp_zip, project_id, db, "Scale AI", cancel_event=cancel_event)

@app.post("/api/projects/{project_id}/import/darwin")
def import_darwin(project_id: int, payload: ImportDarwinIn,
                   user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    cancel_event = threading.Event()
    IMPORT_CANCELS[project_id] = cancel_event
    _rate_limit(_limiter_import, "darwin", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
    if not payload.api_key or not payload.team_slug or not payload.dataset_slug:
        raise HTTPException(400, "api_key, team_slug, dataset_slug обязательны")
    headers = {"Authorization": f"ApiKey {payload.api_key}",
               "Accept": "application/json", "Content-Type": "application/json"}
    base = "https://darwin.v7labs.com/api"
    version_name = payload.version_name or f"db_export_{uuid.uuid4().hex[:8]}"
    gen_url = f"{base}/teams/{payload.team_slug}/datasets/{payload.dataset_slug}/exports"
    body = {"name": version_name, "format": "coco"}
    try:
        r = _http_post_json(gen_url, headers, body, timeout=120)
    except urllib.error.HTTPError as he:
        body_text = ""
        try:
            body_text = he.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise HTTPException(he.code, f"Darwin API: {he.reason} {body_text}")
    except Exception as e:
        raise HTTPException(500, f"Darwin API: {_safe_error_message(e)}")
    export_id = r.get("id") or r.get("export_id") or (r.get("data") or {}).get("id")
    if not export_id:
        raise HTTPException(500, "Darwin не вернул id экспорта")
    download_url = None
    for _ in range(120):
        time.sleep(5)
        try:
            s = _http_get_json(f"{base}/teams/{payload.team_slug}/exports/{export_id}", headers)
        except Exception:
            continue
        status = (s.get("status") or "").lower()
        if status in ("completed", "done", "ready"):
            download_url = s.get("download_url") or s.get("url")
            break
        if status in ("failed", "error"):
            raise HTTPException(500, f"Darwin export {status}: {s.get('message','')}")
    if not download_url:
        raise HTTPException(504, "Darwin: экспорт не завершён за 10 минут")
    with _external_import_tmp("darwin") as tmp_zip:
        _download_to_file(download_url, tmp_zip)
        return _finalize_external_import(tmp_zip, project_id, db, "Darwin", cancel_event=cancel_event)

# ---------------------------------------------------------------------------
# Бэкап проекта
# ---------------------------------------------------------------------------
# moved backup_project
# moved download_backup
def _anns_with_keypoints(db, image_ids: list) -> dict:
    """V8.6.0: {annotation_id: [Keypoint, ...]}. Chunked in_()."""
    if not image_ids:
        return {}
    ann_ids = []
    for _c in _chunks(image_ids, 500):
        for row in db.query(Annotation.id).filter(Annotation.image_id.in_(_c)).all():
            ann_ids.append(row.id)
    if not ann_ids:
        return {}
    out = defaultdict(list)
    for _c in _chunks(ann_ids, 500):
        for kp in db.query(Keypoint).filter(Keypoint.annotation_id.in_(_c)).all():
            out[kp.annotation_id].append(kp)
    return out

def _iname_for_export(img, naming, used):
    if naming == "original":
        stem, _ = _split_name_ext(img.filename)
        stem = INVALID_CHARS_RE.sub('_', stem).strip().rstrip('.') or str(img.id)
        base = stem
        n = 1
        while stem in used:
            stem = f"{base} ({n})"
            n += 1
        used.add(stem)
        return f"{stem}.jpg"
    return f"{img.id}.jpg"

def _cleanup_old_exports(prefix: str, keep: int = 20):
    try:
        files = [(os.path.join(EXPORT_DIR, f), os.path.getmtime(os.path.join(EXPORT_DIR, f)))
                 for f in os.listdir(EXPORT_DIR) if f.startswith(prefix) and f.endswith(".zip")]
        files.sort(key=lambda x: x[1], reverse=True)
        for p, _ in files[keep:]:
            _remove_file_safe(p)
    except Exception as e:
        log.warning("cleanup exports: %s", e)

@app.get("/api/projects/{project_id}/export/yolo")
def export_yolo(project_id: int, naming: str = "numbered", split: str = "none",
                force_pose: bool = False,
                include_meta: bool = False,
                db: Session = Depends(get_db)):
    if naming not in ("original", "numbered"):
        naming = "numbered"
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    object_class = proj.object_class or DEFAULT_OBJECT_CLASS
    class_yaml = object_class.replace("'", "''")
    images = (db.query(ImageModel)
                .filter(ImageModel.project_id == project_id,
                        ImageModel.is_deleted.is_(False)).all())
    if not images:
        raise HTTPException(404, {"key": "error.noImages", "fallback": "No images"})
    buckets = _split_images(images, split)
    use_split = split and split != "none" and (len(buckets["val"]) + len(buckets["test"])) > 0
    zip_path = os.path.join(EXPORT_DIR, f"yolo_project_{project_id}_{naming}_{split}.zip")
    used = set()
    with _atomic_zip(zip_path) as z:
        # [FIX-STAGE2:POSE-YAML] считаем use_pose заранее +
        # пишем kpt_shape/flip_idx в data.yaml (раньше отсутствовали,
        # из-за чего YOLO-pose не мог обучиться по такому yaml)
        _use_pose_for_yaml = force_pose or _project_has_keypoints(db, project_id)
        _kp_extra = ""
        if _use_pose_for_yaml:
            try:
                from config import get_keypoint_schema_for_project as _gk_yaml
                _schema_yaml = _gk_yaml(db, project_id)
                _n_yaml = len(_schema_yaml)
                _flip_yaml = list(range(_n_yaml))
                _kp_extra = (f"kpt_shape: [{_n_yaml}, 3]\n"
                             f"flip_idx: {_flip_yaml}\n")
            except Exception:
                _kp_extra = ""
        if use_split:
            data_yaml = (f"path: .\ntrain: images/train\nval: images/val\n"
                         f"test: images/test\nnc: 1\nnames: ['{class_yaml}']\n"
                         + _kp_extra)
        else:
            data_yaml = (f"path: .\ntrain: images\nval: images\n"
                         f"nc: 1\nnames: ['{class_yaml}']\n"
                         + _kp_extra)
        # [/FIX-STAGE2:POSE-YAML]
        z.writestr("data.yaml", data_yaml)
        try:
            from services.dataset_card_service import generate_dataset_card
            z.writestr("README.md", generate_dataset_card(db, project_id))
        except Exception:
            pass
        try:
            from services.versioning_service import calculate_dataset_hash
            import json as _json
            _ds_hash = calculate_dataset_hash(db, project_id)
            z.writestr("dataset_info.json", _json.dumps({
                "hash": _ds_hash,
                "project_id": project_id,
                "object_class": object_class,
                "exported_at": utcnow().isoformat(),
                "naming": naming,
                "split": split,
            }, ensure_ascii=False, indent=2))
        except Exception:
            pass
        # V8.4.0: параллельно собираем attributes.csv (behavior + animal_id + ts).
        attr_rows = ["image_filename,annotation_index,behavior,animal_id,timestamp_sec"]
        # V8.6.0: определяем, использовать ли pose-формат.
        use_pose = _use_pose_for_yaml  # [FIX-STAGE2:POSE-USE]
        img_ids = [im.id for im in images]
        kps_by_ann = _anns_with_keypoints(db, img_ids) if use_pose else {}
        from config import get_keypoint_schema_for_project as _gk
        _export_schema = _gk(db, project_id) if use_pose else KEYPOINT_SCHEMA

        # Pre-compute iname_map / anns_by_image / kp_by_ann
        _iname_map = {}
        for _bucket_images in buckets.values():
            for _img in _bucket_images:
                _iname_map[_img.id] = _iname_for_export(_img, naming, used)
        _all_img_ids = [im.id for im in images]
        _anns_by_image = defaultdict(list)
        _kp_by_ann = defaultdict(list)
        for _id_chunk in _chunks(_all_img_ids, 500):
            for _a in db.query(Annotation).filter(
                    Annotation.image_id.in_(_id_chunk)).all():
                _anns_by_image[_a.image_id].append(_a)
        _ann_ids_all = [a.id for lst in _anns_by_image.values() for a in lst]
        for _ann_chunk in _chunks(_ann_ids_all, 500):
            for _k in db.query(Keypoint).filter(
                    Keypoint.annotation_id.in_(_ann_chunk)).all():
                _kp_by_ann[_k.annotation_id].append(_k)
        for bucket_name, bucket_images in buckets.items():
            if not bucket_images:
                continue
            sub_img = f"images/{bucket_name}" if use_split else "images"
            sub_lbl = f"labels/{bucket_name}" if use_split else "labels"
            for img in bucket_images:
                if not img.path or not os.path.exists(img.path):
                    log.warning("export_yolo: skip missing image #%d", img.id)
                    continue
                iname = _iname_map[img.id]
                z.write(img.path, f"{sub_img}/{iname}")
                anns = _anns_by_image.get(img.id, [])
                if use_pose:
                    # [FIX-STAGE2:POSE-PAD] force_pad=True → аннотации
                    # без скелетов пишутся нулями, а не как bbox-only
                    # (иначе YOLO-pose падает на несовпадении размерности)
                    lines = [_kp_yolo_row(a, kps_by_ann, _export_schema,
                                          force_pad=True) for a in anns]
                else:
                    lines = [f"0 {a.x:.6f} {a.y:.6f} {a.w:.6f} {a.h:.6f}" for a in anns]
                z.writestr(f"{sub_lbl}/{os.path.splitext(iname)[0]}.txt", "\n".join(lines))
                ts_str = "" if img.timestamp_sec is None else f"{img.timestamp_sec:.3f}"
                for ai, a in enumerate(anns):
                    beh = (a.behavior or "").replace(",", " ")
                    aid = "" if a.animal_id is None else str(a.animal_id)
                    attr_rows.append(f"{iname},{ai},{beh},{aid},{ts_str}")
        # Пустой attributes.csv не пишем (иначе мусор в архиве).
        if len(attr_rows) > 1:
            z.writestr("attributes.csv", "\n".join(attr_rows))

        # V8.5.0: keypoints.csv — отдельный файл для скелета.
        kp_rows = ["image_filename,annotation_index,keypoint_name,x,y,visibility"]
        for bucket_name, bucket_images in buckets.items():
            if not bucket_images:
                continue
            for img in bucket_images:
                iname = _iname_map[img.id]
                anns = _anns_by_image.get(img.id, [])
                for ai, a in enumerate(anns):
                    kps = _kp_by_ann.get(a.id, [])
                    for kp in kps:
                        kp_rows.append(
                            f"{iname},{ai},{kp.name},"
                            f"{kp.x:.6f},{kp.y:.6f},{kp.visibility:.3f}"
                        )
        if len(kp_rows) > 1:
            z.writestr("keypoints.csv", "\n".join(kp_rows))
        if include_meta:
            try:
                import json as _json
                _meta = _build_letterbox_meta(images)
                z.writestr("dataset_meta.json",
                           _json.dumps(_meta, ensure_ascii=False, indent=2))
            except Exception:
                log.exception("dataset_meta.json (yolo) failed")
    suffix = "orig" if naming == "original" else "num"
    suffix += "_split" if use_split else ""
    _cleanup_old_exports("yolo_project_")
    log_status("info", "export",
               f"Экспорт YOLO проекта #{project_id} (класс «{object_class}»): {len(images)} фото")
    # [FIX-STAGE2:WEBHOOK-ASYNC] fire-and-forget: не блокируем
    # скачивание из-за retry × timeout в webhook_service
    try:
        _wh_size = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0
        def _fire_export_webhook(_pid=project_id, _fmt="yolo", _size=_wh_size):
            try:
                from services.webhook_service import dispatch_event as _wh
                _wh(None, _pid, "dataset.exported",
                    {"format": _fmt, "size": _size})
            except Exception:
                pass
        import threading as _th
        _th.Thread(target=_fire_export_webhook, daemon=True,
                   name=f"wh-export-{project_id}").start()
    except Exception:
        pass
    return FileResponse(zip_path, filename=f"yolo_project_{project_id}_{suffix}.zip",
                        media_type="application/zip")

@app.get("/api/projects/{project_id}/export/coco")
def export_coco(project_id: int, naming: str = "numbered", split: str = "none",
                include_meta: bool = False,
                db: Session = Depends(get_db)):
    if naming not in ("original", "numbered"):
        naming = "numbered"
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    object_class = proj.object_class or DEFAULT_OBJECT_CLASS
    images = (db.query(ImageModel)
                .filter(ImageModel.project_id == project_id,
                        ImageModel.is_deleted.is_(False)).all())
    if not images:
        raise HTTPException(404, {"key": "error.noImages", "fallback": "No images"})
    buckets = _split_images(images, split)
    use_split = split and split != "none" and (len(buckets["val"]) + len(buckets["test"])) > 0
    zip_path = os.path.join(EXPORT_DIR, f"coco_project_{project_id}_{naming}_{split}.zip")
    used = set()
    with _atomic_zip(zip_path) as z:
        # V8.6.0: определяем, добавлять ли keypoints в COCO.
        use_kp = _project_has_keypoints(db, project_id)
        _img_ids_all = [im.id for im in images]
        _kps_by_ann = _anns_with_keypoints(db, _img_ids_all) if use_kp else {}
        # кастомная схема
        from config import get_keypoint_schema_for_project as _gk
        _export_schema = _gk(db, project_id) if use_kp else KEYPOINT_SCHEMA
        _kp_names = [k[0] for k in _export_schema]
        _kp_index = {k[0]: i for i, k in enumerate(_export_schema)}
        _kp_skeleton = [[_kp_index[par] + 1, _kp_index[ch] + 1]
                        for (ch, _ru, _en, par) in _export_schema if par]

        for bucket_name, bucket_images in buckets.items():
            if not bucket_images:
                continue
            sub = f"images/{bucket_name}" if use_split else "images"
            cat = {"id": 1, "name": object_class}
            if use_kp:
                cat["keypoints"] = _kp_names
                cat["skeleton"] = _kp_skeleton
            coco = {"images": [], "annotations": [], "categories": [cat]}
            ann_id = 1
            for img in bucket_images:
                if not img.path or not os.path.exists(img.path):
                    log.warning("export_coco: skip missing image #%d", img.id)
                    continue
                iname = _iname_map[img.id]
                coco["images"].append({"id": img.id, "file_name": iname,
                                       "width": img.width, "height": img.height})
                anns = _anns_by_image.get(img.id, [])
                for a in anns:
                    x = a.x * img.width
                    y = a.y * img.height
                    w = a.w * img.width
                    h = a.h * img.height
                    ann = {"id": ann_id, "image_id": img.id, "category_id": 1,
                           "bbox": [x, y, w, h], "area": w * h, "iscrowd": 0}
                    if a.confidence is not None:
                        ann["score"] = a.confidence
                    if use_kp:
                        kps = _kps_by_ann.get(a.id) or []
                        n = len(_export_schema)
                        flat = [0.0] * (n * 3)
                        visible = 0
                        for kp in kps:
                            idx = _kp_index.get(kp.name)
                            if idx is None:
                                continue
                            flat[idx * 3] = float(kp.x) * img.width
                            flat[idx * 3 + 1] = float(kp.y) * img.height
                            v = 2 if float(kp.visibility or 0) >= 0.5 else 1
                            flat[idx * 3 + 2] = v
                            if v == 2:
                                visible += 1
                        ann["keypoints"] = flat
                        ann["num_keypoints"] = visible
                    coco["annotations"].append(ann)
                    ann_id += 1
                z.write(img.path, f"{sub}/{iname}")
            z.writestr(f"coco_{bucket_name}.json", json.dumps(coco, ensure_ascii=False, indent=2))
        if include_meta:
            try:
                import json as _json
                _meta = _build_letterbox_meta(images)
                z.writestr("dataset_meta.json",
                           _json.dumps(_meta, ensure_ascii=False, indent=2))
            except Exception:
                log.exception("dataset_meta.json (coco) failed")
    suffix = "orig" if naming == "original" else "num"
    suffix += "_split" if use_split else ""
    _cleanup_old_exports("coco_project_")
    log_status("info", "export",
               f"Экспорт COCO проекта #{project_id} (класс «{object_class}»): {len(images)} фото")
    # [FIX-STAGE2:WEBHOOK-ASYNC] fire-and-forget
    try:
        _wh_size = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0
        def _fire_export_webhook(_pid=project_id, _fmt="coco", _size=_wh_size):
            try:
                from services.webhook_service import dispatch_event as _wh
                _wh(None, _pid, "dataset.exported",
                    {"format": _fmt, "size": _size})
            except Exception:
                pass
        import threading as _th
        _th.Thread(target=_fire_export_webhook, daemon=True,
                   name=f"wh-export-{project_id}").start()
    except Exception:
        pass
    return FileResponse(zip_path, filename=f"coco_project_{project_id}_{suffix}.zip",
                        media_type="application/zip")

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def _dir_size(path: str) -> int:
    total = 0
    if not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                continue
    return total

# moved storage_info
# moved storage_paths
# moved storage_backup_db
# moved migrate_status
# moved migrate_start
# moved migrate_reset
@app.get("/api/system/ffmpeg")
def system_ffmpeg_status():
    _check_ffmpeg()
    with _FFMPEG_LOCK:
        info = dict(_FFMPEG_PATHS)
    info.update(_ffmpeg_os_info())
    return info

@app.post("/api/system/ffmpeg/set_path")
def system_ffmpeg_set_path(payload: FfmpegPathIn, db: Session = Depends(get_db)):
    p = (payload.path or "").strip()
    # V7.8.1: Windows Explorer "Копировать как путь" оборачивает в кавычки
    if len(p) >= 2 and p[0] == p[-1] and p[0] in ('"', "'", '\u201c', '\u201d', '\u2018', '\u2019'):
        p = p[1:-1].strip()
    elif p and p[0] in ('"', "'", '\u201c', '\u2018'):
        p = p[1:].strip()
    if p and p[-1] in ('"', "'", '\u201d', '\u2019'):
        p = p[:-1].strip()
    if p:
        if not os.path.isfile(p):
            raise HTTPException(400, f"Файл не найден: {p}")
        if not os.access(p, os.X_OK) and os.name != "nt":
            raise HTTPException(400, f"Файл не исполняемый: {p}")
        _ALLOWED_FFMPEG_NAMES = {"ffmpeg", "ffmpeg.exe"}
        _bn = os.path.basename(p).lower()
        if _bn not in _ALLOWED_FFMPEG_NAMES:
            raise HTTPException(400, "Разрешены только ffmpeg/ffmpeg.exe")
        try:
            _r = subprocess.run([p, "-version"], capture_output=True,
                                text=True, timeout=5,
                                creationflags=_SUBPROC_FLAGS)
            _out = (_r.stdout or "") + (_r.stderr or "")
            if _r.returncode != 0 or "ffmpeg version" not in _out.lower():
                raise HTTPException(400, "Файл не является ffmpeg")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Не удалось проверить ffmpeg")
        set_setting(db, SETTING_FFMPEG_PATH, p)
        log_status("info", "settings", f"ffmpeg: {p}")
    else:
        set_setting(db, SETTING_FFMPEG_PATH, "")
        log_status("info", "settings", "ffmpeg: путь сброшен")
    _check_ffmpeg()
    with _FFMPEG_LOCK:
        info = dict(_FFMPEG_PATHS)
    info.update(_ffmpeg_os_info())
    return info

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
# Version moved to routers/system.py

# ---------------------------------------------------------------------------
# Одноразовый backfill
# ---------------------------------------------------------------------------
# moved _backfill_v760
@app.get("/api/projects/{project_id}/validate")
def validate_project(project_id: int, deep: bool = False, db: Session = Depends(get_db)):
    """Валидатор разметки. Проверяет small_box, overlap, out_of_bounds,
    nested_box, aspect + расширенные проверки Stage 1-A:
    single_frame_track, behavior_jitter."""
    project = db.query(Project).filter(Project.id == project_id,
                                        Project.is_deleted.is_(False)).first()
    if not project:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                  "fallback": "Project not found"})

    images = (db.query(ImageModel)
                .filter(ImageModel.project_id == project_id,
                        ImageModel.is_deleted.is_(False))
                .order_by(ImageModel.video_id, ImageModel.frame_index, ImageModel.id)
                .all())

    issues = []
    unannotated = []

    def add_issue(issue_type, image_id, filename, detail):
        issues.append({"type": issue_type, "image_id": int(image_id),
                       "filename": filename or "", "detail": str(detail)[:200]})

    all_anns_by_img = {}
    for im in images:
        anns = db.query(Annotation).filter(Annotation.image_id == im.id).all()
        all_anns_by_img[im.id] = anns
        if not anns:
            unannotated.append({"id": im.id, "filename": im.filename})
            continue

        # 1. small_box
        for a in anns:
            area = float(a.w) * float(a.h)
            if area < MIN_BOX_AREA:
                add_issue("small_box", im.id, im.filename,
                          "area=%.4f < %.4f" % (area, MIN_BOX_AREA))

        # 2. out_of_bounds
        for a in anns:
            if a.x < 0 or a.y < 0 or (a.x + a.w) > 1.0001 or (a.y + a.h) > 1.0001:
                add_issue("out_of_bounds", im.id, im.filename,
                          "x=%.3f y=%.3f w=%.3f h=%.3f" % (a.x, a.y, a.w, a.h))

        # 3. aspect
        for a in anns:
            ww = max(float(a.w), 1e-6)
            hh = max(float(a.h), 1e-6)
            ar = max(ww / hh, hh / ww)
            if ar > MAX_ASPECT:
                add_issue("aspect", im.id, im.filename,
                          "aspect=%.2f > %.2f" % (ar, MAX_ASPECT))

        # 4. overlap
        for i in range(len(anns)):
            for j in range(i + 1, len(anns)):
                a = anns[i]
                b = anns[j]
                iou = _iou_xywh({"x": a.x, "y": a.y, "w": a.w, "h": a.h},
                                {"x": b.x, "y": b.y, "w": b.w, "h": b.h})
                if iou > MAX_OVERLAP_IOU:
                    add_issue("overlap", im.id, im.filename,
                              "iou=%.2f > %.2f" % (iou, MAX_OVERLAP_IOU))
                    break

        # 5. nested_box
        for i in range(len(anns)):
            for j in range(i + 1, len(anns)):
                a = anns[i]
                b = anns[j]
                ix1 = max(a.x, b.x); iy1 = max(a.y, b.y)
                ix2 = min(a.x + a.w, b.x + b.w); iy2 = min(a.y + a.h, b.y + b.h)
                iw = max(0.0, ix2 - ix1); ih = max(0.0, iy2 - iy1)
                inter_area = iw * ih
                min_area = min(a.w * a.h, b.w * b.h) or 1e-6
                ratio = inter_area / min_area
                if ratio >= NESTED_RATIO:
                    add_issue("nested_box", im.id, im.filename,
                              "nested ratio %.2f" % ratio)
                    break

        # [FIX-STAGE:VALIDATOR-V2] motion_blur (deep) + occluded_keypoint (batch)
        # FIX-2: cv2-проверка только в deep-режиме — иначе валидатор
        # декодирует каждый JPEG и превращается в «вечный цикл» на 10k+ кадрах.
        if deep and cv2 is not None:
            try:
                _img_arr = cv2.imread(im.path)
                if _img_arr is not None:
                    _lap_var = float(
                        cv2.Laplacian(_img_arr, cv2.CV_64F).var()
                    )
                    if _lap_var < 100:
                        add_issue(
                            "blurry", im.id, im.filename,
                            "laplacian_var=%.1f < 100" % _lap_var,
                        )
            except Exception:
                pass
        # FIX-3: один batch-запрос вместо N×M.
        _ann_ids = [a.id for a in anns]
        _kp_by_ann = {}
        if _ann_ids:
            try:
                for _kp in (db.query(Keypoint)
                              .filter(Keypoint.annotation_id.in_(_ann_ids))
                              .all()):
                    _kp_by_ann.setdefault(_kp.annotation_id, []).append(_kp)
            except Exception:
                _kp_by_ann = {}
        for _a in anns:
            for _kp in _kp_by_ann.get(_a.id, []):
                try:
                    _vis = float(
                        _kp.visibility
                        if _kp.visibility is not None else 1.0
                    )
                except (TypeError, ValueError):
                    _vis = 1.0
                if _vis < 0.5:
                    add_issue(
                        "occluded_keypoint", im.id, im.filename,
                        "kp=%s visibility=%.2f" % (_kp.name, _vis),
                    )
        # [/FIX-STAGE:VALIDATOR-V2]

    # 6. single_frame_track
    track_sizes = {}
    for im in images:
        for a in all_anns_by_img.get(im.id, []):
            if a.animal_id is not None:
                track_sizes[a.animal_id] = track_sizes.get(a.animal_id, 0) + 1
    for aid, size in track_sizes.items():
        if size == 1:
            for im in images:
                hit = next((a for a in all_anns_by_img.get(im.id, [])
                            if a.animal_id == aid), None)
                if hit is not None:
                    add_issue("single_frame_track", im.id, im.filename,
                              "animal_id=%d has only 1 frame" % aid)
                    break

    # 7. behavior_jitter
    from collections import defaultdict as _dd
    beh_by_track = _dd(list)
    for im in images:
        for a in all_anns_by_img.get(im.id, []):
            if a.animal_id is not None and a.behavior:
                beh_by_track[a.animal_id].append((im.id, im.filename, a.behavior))
    for aid, seq in beh_by_track.items():
        if len(seq) < 5:
            continue
        changes = sum(1 for k in range(1, len(seq)) if seq[k][2] != seq[k - 1][2])
        if changes / len(seq) > 0.5:
            add_issue("behavior_jitter", seq[0][0], seq[0][1],
                      "animal_id=%d behavior changes %d/%d frames" % (aid, changes, len(seq)))

    by_type = {}
    for it in issues:
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1

    return {
        "project_id": project_id,
        "total_issues": len(issues),
        "by_type": by_type,
        "issues": issues[:500],
        "unannotated": unannotated[:200],
        "images_checked": len(images),
    }


@app.get("/api/videos/{video_id}/track/metrics")
def video_track_metrics(video_id: int, db: Session = Depends(get_db)):
    """[PATCH:STAGE2_1] Compute MOTA / IDF1 tracking metrics for a video.

    Ground-truth = annotations with `confidence IS NULL` (typically manual).
    Prediction   = annotations with `confidence IS NOT NULL` (typically auto).
    If the video has no manual annotations, returns `mota=None` with a hint.
    """
    try:
        from eval_tracker import compute_mota, compute_idf1
    except ImportError as e:
        raise HTTPException(501, f"eval_tracker.py unavailable: {e}")

    video = (db.query(Video)
               .filter(Video.id == video_id, Video.is_deleted.is_(False))
               .first())
    if not video:
        raise HTTPException(404, "Video not found")

    frames = (db.query(ImageModel)
                .filter(ImageModel.video_id == video_id,
                        ImageModel.is_deleted.is_(False))
                .order_by(ImageModel.frame_index).all())
    if not frames:
        raise HTTPException(400, "No frames for this video")

    frame_ids = [f.id for f in frames]
    id_to_fidx = {
        f.id: (f.frame_index if f.frame_index is not None else f.id)
        for f in frames
    }

    gt_frames = defaultdict(list)
    pred_frames = defaultdict(list)

    anns = (db.query(Annotation)
              .filter(Annotation.image_id.in_(frame_ids))
              .all())
    for a in anns:
        fidx = id_to_fidx.get(a.image_id, a.image_id)
        entry = {
            "track_id": int(a.animal_id) if a.animal_id is not None else 0,
            "x": float(a.x), "y": float(a.y),
            "w": float(a.w), "h": float(a.h),
        }
        if a.confidence is None:
            gt_frames[fidx].append(entry)
        else:
            pred_frames[fidx].append(entry)

    total_gt = sum(len(v) for v in gt_frames.values())
    total_pred = sum(len(v) for v in pred_frames.values())

    if total_gt == 0:
        return {
            "video_id": video_id,
            "mota": None,
            "idf1": None,
            "gt_count": 0,
            "pred_count": total_pred,
            "reason": "no_manual_ground_truth",
            "hint": "Нужны ручные аннотации (confidence=null) как ground truth",
        }

    try:
        mota = float(compute_mota(gt_frames, pred_frames))
        idf1 = float(compute_idf1(gt_frames, pred_frames))
    except Exception as e:
        log.exception("track metrics failed")
        raise HTTPException(500, f"Metrics computation failed: {e}")

    return {
        "video_id": video_id,
        "mota": round(mota, 4),
        "idf1": round(idf1, 4),
        "gt_count": total_gt,
        "pred_count": total_pred,
        "frames_with_gt": len(gt_frames),
        "frames_with_pred": len(pred_frames),
    }

@app.get("/api/projects/{project_id}/export/agtech_csv")
def export_agtech_csv(project_id: int, db: Session = Depends(get_db)):
    """[PATCH:STAGE2_2] Export behavior events in AgTech CSV format.

    Columns: Timestamp, Camera_ID, Animal_ID, Behavior_Type, Duration_sec, Confidence.
    Events are built by segmenting contiguous (animal_id, video_id, behavior)
    runs and measuring duration as (next_segment_start - segment_start).
    """
    proj = (db.query(Project)
              .filter(Project.id == project_id, Project.is_deleted.is_(False))
              .first())
    if not proj:
        raise HTTPException(404, "Project not found")

    rows = (db.query(ImageModel, Annotation, Video)
              .join(Annotation, Annotation.image_id == ImageModel.id)
              .outerjoin(Video, Video.id == ImageModel.video_id)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False))
              .order_by(Annotation.animal_id,
                        ImageModel.timestamp_sec,
                        ImageModel.frame_index,
                        ImageModel.id)
              .all())

    events = []
    prev_key = None
    seg_start = None
    seg_conf = []
    last_ts = 0.0

    def _flush(end_ts):
        if prev_key is None or seg_start is None:
            return
        aid, vid, beh = prev_key
        duration = max(0.0, (end_ts or 0.0) - seg_start)
        avg_conf = (sum(seg_conf) / len(seg_conf)) if seg_conf else None
        events.append({
            "timestamp": seg_start,
            "camera_id": vid if vid is not None else "n/a",
            "animal_id": aid,
            "behavior": beh,
            "duration": round(duration, 3),
            "confidence": round(avg_conf, 3) if avg_conf is not None else "",
        })

    for im, a, v in rows:
        aid = int(a.animal_id) if a.animal_id is not None else -1
        vid = int(v.id) if v is not None else None
        beh = (a.behavior or "unknown").strip() or "unknown"

        ts = im.timestamp_sec
        if ts is None and im.frame_index is not None and v is not None and v.fps:
            ts = float(im.frame_index) / float(v.fps) if v.fps else None
        if ts is None:
            ts = float(im.id)

        key = (aid, vid, beh)
        if key != prev_key:
            if prev_key is not None:
                _flush(ts)
            prev_key = key
            seg_start = ts
            seg_conf = [float(a.confidence)] if a.confidence is not None else []
        elif a.confidence is not None:
            seg_conf.append(float(a.confidence))
        last_ts = ts

    if prev_key is not None:
        _flush(last_ts)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=",", lineterminator="\n")
    w.writerow(["Timestamp", "Camera_ID", "Animal_ID",
                "Behavior_Type", "Duration_sec", "Confidence"])
    for e in events:
        w.writerow([
            f"{e['timestamp']:.3f}" if isinstance(e["timestamp"], (int, float))
            else e["timestamp"],
            e["camera_id"],
            e["animal_id"],
            e["behavior"],
            f"{e['duration']:.3f}",
            e["confidence"],
        ])

    body = buf.getvalue().encode("utf-8-sig")
    log_status("info", "export",
               f"AgTech CSV: project #{project_id}, {len(events)} events")
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f"attachment; filename=agtech_events_project_{project_id}.csv"},
    )

class UserIn(BaseModel):
    username: str
    full_name: str = ""
    password: str = ""
    role: str = "annotator"


# _hash_password_simple удалён (не использовался).

def require_role(*allowed_roles):
    """[PATCH:STAGE2_3] Dependency factory for role checks. [STAGE1:require-role-real]"""
    def _checker(user: dict = Depends(get_current_user)):
        if user.get("local"):
            return user
        if user.get("role") not in allowed_roles:
            raise HTTPException(403, {"key": "error.forbidden",
                                      "fallback": "Недостаточно прав"})
        return user
    return _checker


@app.get("/api/users", dependencies=[Depends(require_permission("project.manage"))])
def list_users(db: Session = Depends(get_db)):
    from models import User
    rows = db.query(User).order_by(User.id).all()
    return {"items": [
        {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
         "is_active": bool(u.is_active), "temp_password": u.temp_password,
         "created_at": u.created_at.isoformat() if u.created_at else None}
        for u in rows
    ]}


@app.post("/api/users")
def create_user(payload: UserIn, db: Session = Depends(get_db),
                _user: dict = Depends(require_permission("user.manage"))):
    # argon2 + temp password + must_change_password
    from models import User as _User
    from services.auth_service import hash_password as _hp
    import secrets as _sec
    username = (payload.username or "").strip()
    if not username or len(username) < 3:
        raise HTTPException(400, {"key": "error.usernameTooShort",
                                  "fallback": "username must be ≥3 chars"})
    valid_roles = ("admin", "manager", "annotator", "reviewer")
    if payload.role not in valid_roles:
        raise HTTPException(400, {"key": "error.invalidRole",
                                  "fallback": f"role must be one of: {valid_roles}"})
    if db.query(_User).filter(_User.username == username).first():
        raise HTTPException(409, {"key": "error.usernameTaken",
                                  "fallback": "username already exists"})
    if payload.password:
        if len(payload.password) < 8:
            raise HTTPException(400, "Пароль должен быть не менее 8 символов")
        temp_pw = payload.password
        generated = False
    else:
        temp_pw = _sec.token_urlsafe(12)
        generated = True
    full_name = (payload.full_name or "").strip()
    u = _User(
        username=username,
        full_name=full_name,
        password_hash=_hp(temp_pw),
        role=payload.role,
        is_active=1,
        temp_password=temp_pw,
        created_at=utcnow(),
    )
    try:
        u.must_change_password = 1
    except Exception:
        pass
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        # Stage 5.7 — race: два параллельных POST /api/users
        db.rollback()
        raise HTTPException(409, {"key": "error.usernameTaken",
                                  "fallback": "username already exists"})
    db.refresh(u)
    log_status("info", "system",
               f"RBAC: user {username} ({payload.role}) created by "
               f"{_user.get('username')}")
    return {"id": u.id, "username": u.username, "role": u.role,
            "temp_password": temp_pw if generated else None,
            "must_change_password": True}


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db),
                _user: dict = Depends(require_permission("user.manage"))):
    # protect last admin, cascade sessions
    from models import User as _User, UserProjectAccess
    try:
        from models import Session as _SessModel
    except Exception:
        _SessModel = None
    u = db.query(_User).filter(_User.id == user_id).first()
    if not u:
        raise HTTPException(404, {"key": "error.userNotFound",
                                  "fallback": "User not found"})
    if u.role == "admin":
        admins = db.query(_User).filter(_User.role == "admin",
                                        _User.is_active == 1).count()
        if admins <= 1:
            raise HTTPException(400, {"key": "error.lastAdmin",
                                      "fallback": "Cannot delete the last admin"})
    db.query(UserProjectAccess) \
        .filter(UserProjectAccess.user_id == user_id) \
        .delete(synchronize_session=False)
    if _SessModel is not None:
        try:
            db.query(_SessModel) \
                .filter(_SessModel.user_id == user_id) \
                .delete(synchronize_session=False)
        except Exception:
            pass
    db.delete(u)
    db.commit()
    log_status("warning", "system",
               f"RBAC: user {u.username} deleted by {_user.get('username')}")
    return {"status": "ok"}

class ValidateBehaviorIn(BaseModel):
    image_id: int
    true_behavior: str
    annotation_id: Optional[int] = None
    validated_by: Optional[str] = None


_VALID_BEHAVIORS = {"eat", "walk", "lie", "drink", "stand", "active"}





# ══════════════════════════════════════════════════════════════════════════
 # Простая и надежная авторизация
# ══════════════════════════════════════════════════════════════════════════


# ==============================================================================
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
