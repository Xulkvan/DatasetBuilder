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
from services.url_safety import is_safe_external_url  # [STAGE5:ssrf-import]
# [STAGE-SEC1:imports]
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

from sqlalchemy import inspect, text, func  # [PATCH:STAGE1_SQLALCHEMY_IMPORTS]
from sqlalchemy.orm import Session  # [PATCH:STAGE1_SQLALCHEMY_IMPORTS]
from sqlalchemy.exc import IntegrityError

from database import SessionLocal, Base, engine, get_db, DB_ENGINE, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME


# V13.1.0: восстановленные сервисы

from models import Project, ImageModel, Annotation, Keypoint, Setting, Tag, ImageTag, Video, Stream, Webhook

from schemas import *
from config import *
from config import _HEX_COLOR_RE
from config import _norm_behavior, _norm_animal_id  # [STAGE6:CONSTANTS-MOVED]  # noqa: F401  [STAGE4:re-export]
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
# [FIX:bootstrap-thread-dead] module-ref for BOOTSTRAP_THREAD
from services import bootstrap_service as _bootstrap_svc
from services.trash_service import (
    cleanup_expired_trash,
    cleanup_expired_data,  # [PATCH:STAGE2-F-02]
    _start_trash_cleaner_thread,
)
from services.train_service import (
    prepare_training_dataset_pose,
)
from services.file_service import (
    _safe_model_path, _sanitize_model_name, _unique_model_name_from_disk, _is_simple_filename,
    sanitize_display_name, _unique_name_mem,
    _detect_image_format, _split_name_ext, letterbox,
    _open_image_safe  # [STAGE1.2:import-open-image-safe]
)
from services.image_service import (
    _remove_file_safe, _queue_thumb, _invalidate_stats_cache, _invalidate_phash_index, _iou_xywh, dedup_boxes,
    phash_hex, _hex_to_int, _hamming_int,
    _get_phash_index, _find_duplicates_via_index,
)
# [PATCH:STAGE6-F15-C18] shared error utilities
from services.errors import _safe_error_message, _db_commit_safe
# [PATCH:STAGE6-PART2-4.8] startup tasks
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
    IMPORT_PROGRESS,  # [PATCH:REFACTOR-FIX]
    # [PATCH:REFACTOR-FIX-V2] re-exports for backward compat with tests that do `from app import _safe_extract_zip` (test_path_traversal.py / test_zip_bomb.py).
    _safe_extract_zip,
    _collect_image_files,
    _update_import_progress,
)
# [PATCH:RECOMMENDATIONS-PROCESS-DATASET-ZIP-DELEGATE] Thin delegate:
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
# [PATCH:STAGE4_APP_SERVICE_IMPORTS]
from services.track_service import (
    TRACK_STATE, TRACK_LOCK, TRACK_STOP, TRACK_EVENT,
    _track_snapshot, _track_worker,
)
from services.motion_service import _check_motion, _check_motion_batch
# [/PATCH:STAGE4_APP_SERVICE_IMPORTS]

from logger import (
    log_status, utcnow,
)

# [PATCH:STAGE4-F-08-metrics-import]
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


# [STAGE3:DEDUP-EXPORT] — функции вынесены в services/export_service.py
from services.export_service import (
    _build_letterbox_meta,
    _split_images,
    _kp_yolo_row,
    _project_has_keypoints,
)


# [PATCH:STAGE3_CHUNKS_HELPER]
def _chunks(seq, n: int = 500):
    """Разбивает последовательность на чанки по n (лимит SQLite — 999 параметров)."""
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
# [/PATCH:STAGE3_CHUNKS_HELPER]

# [PATCH:STAGE2:E2-EXPORT-ATOMIC-HELPER]
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
# [/PATCH:STAGE2:E2-EXPORT-ATOMIC-HELPER]

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
# [STAGE2:keypoint-schema-migration] CREATE TABLE IF NOT EXISTS
# project_keypoint_schemas. Дополняет Base.metadata.create_all для случаев,
# когда модель ProjectKeypointSchema была добавлена после первичной инициализации.
# ============================================================================
# [/STAGE2:keypoint-schema-migration]


# ============================================================================
# [STAGE3:stream-migrations] is_stream_frame в images + CREATE TABLE streams.
# ============================================================================
# [PATCH:FIX_LOCK_SESSION_ID_MIGRATION]
# [/PATCH:FIX_LOCK_SESSION_ID_MIGRATION]

# [/STAGE3:stream-migrations]

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# [STAGE1:CV2-IMPORT] OpenCV для проверки motion_blur
try:
    import cv2
except ImportError:
    cv2 = None
# [/STAGE1:CV2-IMPORT]

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

# [PATCH:STAGE4_APP_PATHS]
# Все пути — из config.py (единый источник правды).
# BASE_DIR / DATA_ROOT / UPLOAD_DIR / MODEL_DIR / THUMB_DIR и т.д.
# уже импортированы через `from config import *` в шапке файла.
INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")
# [/PATCH:STAGE4_APP_PATHS]
STYLE_CSS_PATH = os.path.join(BASE_DIR, "style.css")
APP_JS_PATH = os.path.join(BASE_DIR, "app.js")
I18N_JS_PATH = os.path.join(BASE_DIR, "i18n.js")


# [STAGE6:CONSTANTS-MOVED] Дубли устранены в Stage 6.4.
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
# [PATCH:STAGE6-PART2] moved to zip_import_service

# ---------------------------------------------------------------------------
# Импорт разметки — парсеры
# ---------------------------------------------------------------------------
def _basename_no_ext(name: str) -> str:
    base = os.path.basename(name or "")
    stem, _ = _split_name_ext(base)
    return stem.lower()

def _px_xywh_to_norm(x, y, w, h, iw, ih):
    if iw <= 0 or ih <= 0:
        return None
    return {"x": x / iw, "y": y / ih, "w": w / iw, "h": h / ih}

def _append_annotation(out: dict, key: str, x: float, y: float, w: float, h: float,
                       label: str = DEFAULT_OBJECT_CLASS,
                       confidence: Optional[float] = None):
    if not key:
        return
    out[key].append({
        "x": max(0.0, min(1.0, float(x))),
        "y": max(0.0, min(1.0, float(y))),
        "w": max(0.0, min(1.0, float(w))),
        "h": max(0.0, min(1.0, float(h))),
        "label": label,
        "confidence": confidence,
    })
# [PATCH:STAGE6-PART2] moved parse_coco
def parse_coco(json_path: str, default_label: str = DEFAULT_OBJECT_CLASS):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    imgs = {i["id"]: i for i in data.get("images", [])}
    out = defaultdict(list)
    for ann in data.get("annotations", []):
        img = imgs.get(ann.get("image_id"))
        if not img:
            continue
        bbox = ann.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x, y, w, h = bbox
        norm = _px_xywh_to_norm(x, y, w, h, img.get("width", 0), img.get("height", 0))
        if not norm:
            continue
        _append_annotation(out, _basename_no_ext(img.get("file_name", "")),
                           norm["x"], norm["y"], norm["w"], norm["h"],
                           default_label, ann.get("score"))
    return out
# [PATCH:STAGE6-PART2] moved parse_yolo
def parse_yolo(zip_dir: str, default_label: str = DEFAULT_OBJECT_CLASS):
    out = defaultdict(list)
    labels_dirs = []
    for root, dirs, files in os.walk(zip_dir):
        if os.path.basename(root) == "labels":
            labels_dirs.append(root)
            continue
        has_txt = any(f.lower().endswith(".txt") for f in files)
        has_img = any(_is_image_ext(f) for f in files)
        if has_txt and has_img:
            labels_dirs.append(root)
    if not labels_dirs:
        return out
    seen = set()
    processed = 0
    for labels_dir in labels_dirs:
        for fn in os.listdir(labels_dir):
            if not fn.lower().endswith(".txt"):
                continue
            stem = _basename_no_ext(fn)
            if stem in seen:
                continue
            seen.add(stem)
            processed += 1
            path = os.path.join(labels_dir, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) < 5:
                            continue
                        try:
                            _cls = int(parts[0])
                            xc, yc, w, h = map(float, parts[1:5])
                        except ValueError:
                            continue
                        _append_annotation(out, stem,
                                           xc - w / 2, yc - h / 2, w, h,
                                           default_label, None)
            except OSError:
                log.exception("parse_yolo: cannot read %s", path)
    log.info("parse_yolo: найдено %d label-директорий, обработано %d .txt",
             len(labels_dirs), processed)
    return out
# [PATCH:STAGE6-PART2] moved parse_cvat
def parse_cvat(xml_path: str, default_label: str = DEFAULT_OBJECT_CLASS):
    out = defaultdict(list)
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError:
        return out
    for img in root.findall("image"):
        iw = float(img.get("width") or 0)
        ih = float(img.get("height") or 0)
        key = _basename_no_ext(img.get("name", ""))
        if not key or iw <= 0 or ih <= 0:
            continue
        for box in img.findall("box"):
            try:
                xtl = float(box.get("xtl"))
                ytl = float(box.get("ytl"))
                xbr = float(box.get("xbr"))
                ybr = float(box.get("ybr"))
            except (TypeError, ValueError):
                continue
            x, y = xtl, ytl
            w, h = xbr - xtl, ybr - ytl
            if w <= 0 or h <= 0:
                continue
            norm = _px_xywh_to_norm(x, y, w, h, iw, ih)
            if not norm:
                continue
            _append_annotation(out, key, norm["x"], norm["y"], norm["w"], norm["h"],
                               default_label)
    return out

_UNSUPPORTED_LS_TYPES = set()
# [PATCH:STAGE6-PART2] moved parse_label_studio
def parse_label_studio(json_path: str, default_label: str = DEFAULT_OBJECT_CLASS):
    out = defaultdict(list)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return out
    if not isinstance(data, list):
        data = [data]
    for item in data:
        img_path = ((item.get("data") or {}).get("image") or "")
        key = _basename_no_ext(img_path)
        if not key:
            continue
        for ann_block in item.get("annotations", []) or []:
            for r in ann_block.get("result", []) or []:
                if r.get("type") != "rectanglelabels":
                    t = r.get("type", "unknown")
                    if t not in _UNSUPPORTED_LS_TYPES:
                        _UNSUPPORTED_LS_TYPES.add(t)
                        log.info("parse_label_studio: пропускаю тип %r", t)
                    continue
                val = r.get("value", {})
                _append_annotation(out, key,
                                   val.get("x", 0) / 100,
                                   val.get("y", 0) / 100,
                                   val.get("width", 0) / 100,
                                   val.get("height", 0) / 100,
                                   default_label)
    return out
# [PATCH:STAGE6-PART2] moved detect_format
def detect_format(zip_dir: str):
    files = []
    for root, dirs, fs in os.walk(zip_dir):
        for f in fs:
            files.append(os.path.join(root, f))
    for p in files:
        if p.lower().endswith(".json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "annotations" in data and "images" in data:
                    return ("coco", p)
            except Exception:
                pass
    for p in files:
        if p.lower().endswith(".xml"):
            try:
                with open(p, "rb") as f:
                    head = f.read(1024)
                if b"<annotations" in head or b"<image" in head:
                    return ("cvat", p)
            except Exception:
                pass
    for p in files:
        if p.lower().endswith(".json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data and isinstance(data[0], dict) and "annotations" in data[0]:
                    return ("ls", p)
                if isinstance(data, dict) and "annotations" in data:
                    return ("ls", p)
            except Exception:
                pass
    for root, dirs, fs in os.walk(zip_dir):
        if os.path.basename(root) == "labels":
            return ("yolo", root)
    return (None, None)



# ---------------------------------------------------------------------------
# Converters к COCO
# ---------------------------------------------------------------------------
# [PATCH:STAGE6-PART2] moved _labelbox_to_coco
# [PATCH:STAGE6-PART2] moved _scale_to_coco
# [PATCH:STAGE6-PART2] moved _coco_to_zip
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
# [STAGE4:train-service-import] Training state & thread moved to
# services/train_service.py to break the app.py <-> routers/api_v2.py cycle.
from services.train_service import (
    TRAIN_STATE, TRAIN_LOCK, TRAIN_EVENT,
    _train_reset, _train_snapshot,
    prepare_training_dataset,
    _handle_train_line,  # noqa: F401  (kept for API compatibility)
    run_training_thread as _run_training_thread,
)
# [STAGE4:train-process-fix] TRAIN_PROCESS is rebindable inside
# run_training_thread — read via module, not via from-import.
from services import train_service as _train_svc



# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

# [PATCH:STAGE6-PART2] moved _restore_active_streams
# [PATCH:STAGE6-PART2] moved _warm_yolo_cache
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        n = cleanup_expired_trash(db)
        if n:
            log.info("Удалено устаревших объектов из корзины: %d", n)
        # [PATCH:STAGE2-F-02-startup] retention при старте
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
    # [PATCH:STAGE1:E1-COOKIE] warn about team-mode + non-secure cookies
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
    # [FIX:v1341-backend] Восстановление активных стримов
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


# [PATCH:STAGE6-F15-C18] moved to services/errors.py
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

# [PATCH:STAGE4-F-08-prometheus-instrument]
if _PROMETHEUS_AVAILABLE:
    try:
        _Instrumentator().instrument(app).expose(
            app, endpoint="/api/metrics", include_in_schema=False,
        )
        log.info("Prometheus /api/metrics enabled")
    except Exception as _e_prom:
        log.warning("Prometheus instrumentation failed: %s", _e_prom)


# [PATCH:STAGE1:E1-METRICS] Basic-auth gate for /api/metrics
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

# [PATCH:AUTH-MODE-FIX-V22]
# [STAGE2:auth-dedupe] — Единый источник auth-зависимостей — services.auth_service.
# Локальные дубли (auth-mode helper + user/permission deps) удалены.
from fastapi import Request, Depends, HTTPException, Body, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import SessionLocal
import os

from services.auth_service import get_current_user, require_permission

@app.middleware("http")
async def _global_auth_middleware(request: Request, call_next):
    # [PATCH:STAGE5-auth-request-id] Убедиться, что request_id
    # установлен ДО любых логов (defensive: если add_request_id
    # окажется inner — здесь fallback).
    try:
        _ensure_request_id(request)
    except Exception:
        pass
    path = request.url.path

    # 1. Всегда пытаемся прочитать сессию (даже для публичных путей)
    u = request.cookies.get("pdb_session")
    # [PATCH:STAGE1:E1-V2-USER] preserve user context set by _v2_api_key_guard
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
        # [PATCH:STAGE1-F-04] гарантируем pdb_csrf cookie в local mode
        resp = await call_next(request)
        try:
            if not request.cookies.get("pdb_csrf"):
                from services.auth_service import set_csrf_cookie
                set_csrf_cookie(resp, request)
        except Exception:
            pass
        return resp

    # 3. Публичные пути
    # [PATCH:STAGE5-health-public] /api/health публичен для Docker healthcheck.
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
                # [PATCH:STAGE5-auth-401-rid] дублируем в STATUS_LOG с rid
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
        # [PATCH:STAGE1-F-13] fail-closed в team mode
        if resolve_auth_mode(DB_ENGINE) != "local":
            return JSONResponse(
                status_code=500,
                content={"detail": {"key": "error.rbacError",
                                     "fallback": "Внутренняя ошибка проверки прав"}})

    return await call_next(request)
# [/PATCH:AUTH-MODE-FIX-V22]

from routers import system, projects, tags, images, ml
app.include_router(system.router)
app.include_router(projects.router)
app.include_router(tags.router)
app.include_router(images.router)
app.include_router(ml.router)
# [V13.2.0:pipeline-router]
from routers import pipeline as _pipeline_router
app.include_router(_pipeline_router.router)
# [STAGE2:api-v2-router]
from routers import api_v2 as _api_v2_router
app.include_router(_api_v2_router.router)
# [STAGE3:webhooks-router]
from routers import webhooks as _webhooks_router
app.include_router(_webhooks_router.router)
# [STAGE1:auth-router] Team Edition: auth + setup routers.
from routers import auth as _auth_router
app.include_router(_auth_router.router)
from routers import setup as _setup_router
app.include_router(_setup_router.router)

# [PATCH:STAGE6-PART2-4.7] Storage router
from routers import storage as _storage_router
app.include_router(_storage_router.router)

# [PATCH:STAGE6-PART2-4.4] Backup router
from routers import backup as _backup_router
app.include_router(_backup_router.router)

# [PATCH:STAGE6-PART2-4.3] Batch router
from routers import autolabel_batch as _batch_router
app.include_router(_batch_router.router)

# [PATCH:STAGE6-F03-4.2] Training router
from routers import train as _train_router
app.include_router(_train_router.router)
# [PATCH:STAGE2:E2-APP-DEDUP] use _read_run_metadata from routers/train.py
from routers.train import _read_run_metadata  # noqa: E402,F811

# [PATCH:STAGE6-F03-4.1] Models router
from routers import models as _models_router
app.include_router(_models_router.router)
# [/STAGE1:auth-router]

# [STAGE4:assignments-router-reg]
from routers import assignments as _assignments_router
app.include_router(_assignments_router.router)
# [/STAGE4:assignments-router-reg]

# [PATCH:STAGE2-C2] CSV-экспорт: stats.csv / files.csv / boxes.csv
from routers import exports_csv as _exports_csv_router
app.include_router(_exports_csv_router.router)

# [STAGE5:locks-router-reg]
from routers import locks as _locks_router
app.include_router(_locks_router.router)
# [/STAGE5:locks-router-reg]

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

# [PATCH:STAGE5-request-id-middleware] Stage 5.4 — request_id + contextvar.
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

# [STAGE2:api-key-middleware]
@app.middleware("http")
async def _v2_api_key_guard(request: Request, call_next):
    """Bearer-токен для /api/v2/* если API_KEY задан."""
    path = request.url.path
    if path.startswith("/api/v2/"):
        # [PATCH:STAGE1-F-01] fail-closed: no API_KEY → 503
        try:
            from services.api_key import validate_api_key
            validate_api_key(request, required=True)
        except HTTPException as _he:
            return JSONResponse(status_code=_he.status_code,
                                content={"detail": _he.detail})
        # [PATCH:STAGE1:E1-V2-USER] service user context for downstream audit
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

# [PATCH:STAGE5-health-endpoint] Stage 5.3 — health-эндпоинт.
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

# MOVED to routers/ (Stage 3.11): @app.post("/api/videos/{video_id}/track")
def video_track_start(video_id: int, db: Session = Depends(get_db)):
    """Запускает ByteTrack-трекинг по кадрам видео."""
    global TRACK_THREAD
    # [PATCH:STAGE2:E2-TRACK-RACE] атомарный check: сразу ставим "starting"
    with TRACK_LOCK:
        if TRACK_STATE["status"] in ("running", "starting"):
            raise HTTPException(409, "Трекинг уже идёт")
        TRACK_STATE["status"] = "starting"
        TRACK_STATE["message"] = "Starting..."
    try:
        # [V13.2.0:pipeline-track-guard]
        try:
            from services.pipeline_service import PIPELINE_STATE as _PS
            if _PS.get("status") in ("running", "stopping"):
                raise HTTPException(409, "Идёт полная разметка (pipeline). Дождитесь окончания.")
        except HTTPException:
            raise
        except Exception:
            pass
        video = db.query(Video).filter(Video.id == video_id,
                                        Video.is_deleted.is_(False)).first()
        if not video:
            raise HTTPException(404, "Видео не найдено")
        project = db.query(Project).filter(Project.id == video.project_id).first()
        if not project:
            raise HTTPException(404, "Проект не найден")
        frames_count = (db.query(func.count(ImageModel.id))
                          .filter(ImageModel.video_id == video_id,
                                  ImageModel.is_deleted.is_(False))
                          .scalar() or 0)
        if frames_count == 0:
            raise HTTPException(400, "У этого видео нет кадров")
        model_path = get_active_model_path(db)
        if not model_path:
            raise HTTPException(501, "Нет активной YOLO-модели. Загрузи или обучи.")

        TRACK_STOP.clear()
        with TRACK_LOCK:
            TRACK_STATE.update({
                "status": "running", "video_id": video_id,
                "total": int(frames_count), "done": 0, "failed": 0,
                "tracks": 0, "assignments": 0,
                "message": "Starting...",
                "started_at": utcnow().isoformat(), "finished_at": None,
            })
        TRACK_EVENT.set()
        t = threading.Thread(
            target=_track_worker,
            args=(video_id, video.project_id, model_path),
            daemon=True, name="tracker",
        )
        TRACK_THREAD = t
        t.start()
        return {"status": "started", "total": int(frames_count)}
    except Exception:
        with TRACK_LOCK:
            if TRACK_STATE.get("status") == "starting":
                TRACK_STATE["status"] = "idle"
                TRACK_STATE["message"] = ""
        TRACK_EVENT.set()
        raise

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

# MOVED to routers/ (Stage 3.11): @app.get("/api/projects/{project_id}/tracks")
def list_project_tracks(project_id: int, db: Session = Depends(get_db)):
    """Список треков проекта: animal_id, кол-во кадров, превью, доминирующее поведение."""
    # V11.9.0: N+1 fix. 3 запроса (tracks + first_images + behaviors) вместо 2N+1.
    rows = (db.query(
                Annotation.animal_id,
                func.count(func.distinct(ImageModel.id)).label("frames_count"),
                func.min(ImageModel.id).label("first_image_id"),
            )
              .join(ImageModel, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False),
                      Annotation.animal_id.isnot(None))
              .group_by(Annotation.animal_id)
              .order_by(Annotation.animal_id)
              .all())

    if not rows:
        return {"items": [], "total": 0}

    first_ids = [int(r.first_image_id) for r in rows if r.first_image_id]
    first_imgs = {}
    if first_ids:
        first_imgs = {
            iid: fname for iid, fname in
            db.query(ImageModel.id, ImageModel.filename)
              .filter(ImageModel.id.in_(first_ids)).all()
        }

    beh_rows = (db.query(Annotation.animal_id, Annotation.behavior,
                         func.count(Annotation.id).label("cnt"))
                  .join(ImageModel, Annotation.image_id == ImageModel.id)
                  .filter(ImageModel.project_id == project_id,
                          ImageModel.is_deleted.is_(False),
                          Annotation.animal_id.isnot(None),
                          Annotation.behavior.isnot(None))
                  .group_by(Annotation.animal_id, Annotation.behavior)
                  .all())
    top_beh = {}
    _best_cnt = {}
    for aid, beh, cnt in beh_rows:
        aid = int(aid)
        cnt = int(cnt or 0)
        if cnt > _best_cnt.get(aid, 0):
            _best_cnt[aid] = cnt
            top_beh[aid] = beh

    out = []
    for r in rows:
        aid = int(r.animal_id)
        first_id = int(r.first_image_id) if r.first_image_id else None
        out.append({
            "animal_id": aid,
            "frames_count": int(r.frames_count or 0),
            "first_image_id": first_id,
            "first_filename": first_imgs.get(first_id),
            "top_behavior": top_beh.get(aid),
        })
    return {"items": out, "total": len(out)}

# MOVED to routers/ (Stage 3.11): @app.post("/api/images/{image_id}/link_from_prev")
def link_from_prev(image_id: int,
                    iou_threshold: float = 0.5,
                    db: Session = Depends(get_db)):
    """Копирует animal_id с предыдущего кадра видео по IoU (ручная правка)."""
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
    if img.video_id is None or img.frame_index is None:
        raise HTTPException(400, "У этого изображения нет video_id / frame_index")

    # Предыдущий кадр того же видео
    prev_img = (db.query(ImageModel)
                  .filter(ImageModel.video_id == img.video_id,
                          ImageModel.frame_index < img.frame_index,
                          ImageModel.is_deleted.is_(False))
                  .order_by(ImageModel.frame_index.desc())
                  .first())
    if not prev_img:
        return {"linked": 0, "reason": "no_prev_frame"}

    prev_anns = (db.query(Annotation)
                   .filter(Annotation.image_id == prev_img.id,
                           Annotation.animal_id.isnot(None))
                   .all())
    if not prev_anns:
        return {"linked": 0, "reason": "no_aid_on_prev"}

    cur_anns = (db.query(Annotation)
                  .filter(Annotation.image_id == img.id).all())
    linked = 0
    details = []
    for a in cur_anns:
        best = None
        best_iou = 0.0
        for p in prev_anns:
            iou = _iou_xywh(
                {"x": a.x, "y": a.y, "w": a.w, "h": a.h},
                {"x": p.x, "y": p.y, "w": p.w, "h": p.h},
            )
            if iou > best_iou:
                best_iou = iou
                best = p
        if best is None or best_iou < iou_threshold:
            continue
        if a.animal_id == best.animal_id:
            continue
        old_aid = a.animal_id
        a.animal_id = best.animal_id
        linked += 1
        details.append({
            "ann_id": a.id,
            "old_animal_id": old_aid,
            "new_animal_id": int(best.animal_id),
            "iou": round(best_iou, 3),
        })
    if linked:
        db.commit()
        log_status("info", "video",
                   "Link from prev: image #%d, привязано %d" % (img.id, linked))
    return {"linked": linked,
            "prev_image_id": prev_img.id,
            "details": details}

# MOVED to routers/ (Stage 3.11): @app.get("/api/projects/{project_id}/navigate_with_aid")
def navigate_with_aid(project_id: int,
                       from_image_id: int,
                       animal_id: int,
                       dir: str = "next",
                       db: Session = Depends(get_db)):
    """Ищет следующий/предыдущий кадр того же видео, где есть эта animal_id."""
    img = db.query(ImageModel).filter(ImageModel.id == from_image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
    if img.video_id is None or img.frame_index is None:
        return {"found": False, "reason": "no_video"}

    d = (dir or "next").lower()
    q = (db.query(ImageModel.id, ImageModel.frame_index)
           .join(Annotation, Annotation.image_id == ImageModel.id)
           .filter(ImageModel.project_id == project_id,
                   ImageModel.video_id == img.video_id,
                   ImageModel.is_deleted.is_(False),
                   Annotation.animal_id == int(animal_id),
                   ImageModel.id != img.id))
    if d == "prev":
        q = q.filter(ImageModel.frame_index < img.frame_index) \
             .order_by(ImageModel.frame_index.desc())
    else:
        q = q.filter(ImageModel.frame_index > img.frame_index) \
             .order_by(ImageModel.frame_index.asc())
    row = q.first()
    if not row:
        return {"found": False, "reason": "end_of_track"}
    return {"found": True, "image_id": int(row.id),
            "frame_index": int(row.frame_index)}


# [PATCH:STAGE4_APP_MOTION_BLOCK]
# _check_motion / _check_motion_batch перенесены в services/motion_service.py
# _check_motion_ex удалён.
# [/PATCH:STAGE4_APP_MOTION_BLOCK]
# MOVED to routers/ (Stage 3.11): @app.get("/api/images/{image_id}/motion_vectors")
def motion_vectors_all(image_id: int, db: Session = Depends(get_db)):
    """V8.8.5: векторы движения для ВСЕХ рамок с animal_id.

    Возвращает:
      {
        "items": {idx: {found, ...}},
        "summary": {total_with_aid, found, missing},
      }
    """
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound",
                                 "fallback": "Image not found"})
    if img.video_id is None or img.frame_index is None:
        return {"items": {}, "summary": {"total_with_aid": 0, "found": 0, "missing": 0},
                "reason": "no_video"}
    # V8.8.6: batch вместо N+1 запросов.
    out = _check_motion_batch(db, image_id)
    found = sum(1 for v in out.values() if v.get("found"))
    missing = sum(1 for v in out.values() if not v.get("found"))
    return {
        "items": out,
        "summary": {
            "total_with_aid": found + missing,
            "found": found,
            "missing": missing,
        },
    }

# MOVED to routers/ (Stage 3.11): @app.get("/api/projects/{project_id}/tracks/{animal_id}/frames")
def track_frames(project_id: int, animal_id: int,
                 db: Session = Depends(get_db)):
    """V8.8.4: список кадров одного трека (в порядке frame_index)."""
    rows = (db.query(ImageModel.id, ImageModel.frame_index,
                     ImageModel.filename, ImageModel.timestamp_sec,
                     ImageModel.video_id, Annotation.behavior,
                     Annotation.x, Annotation.y, Annotation.w, Annotation.h)
              .join(Annotation, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False),
                      Annotation.animal_id == int(animal_id))
              .order_by(ImageModel.video_id, ImageModel.frame_index).all())
    items = [{
        "image_id": int(r.id),
        "frame_index": int(r.frame_index) if r.frame_index is not None else None,
        "video_id": r.video_id,
        "filename": r.filename,
        "timestamp_sec": r.timestamp_sec,
        "behavior": r.behavior,
        "bbox": {"x": r.x, "y": r.y, "w": r.w, "h": r.h},
    } for r in rows]
    return {"items": items, "total": len(items), "animal_id": int(animal_id)}

# MOVED to routers/ (Stage 3.11): @app.get("/api/projects/{project_id}/tracks/export")
def export_tracks(project_id: int, format: str = "json",
                   video_id: Optional[int] = None,
                   db: Session = Depends(get_db)):
    """V8.8.4: экспорт треков проекта в JSON или CSV."""
    fmt = (format or "json").lower()
    if fmt not in ("json", "csv"):
        raise HTTPException(400, "format должен быть json или csv")

    q = (db.query(ImageModel, Annotation)
           .join(Annotation, Annotation.image_id == ImageModel.id)
           .filter(ImageModel.project_id == project_id,
                   ImageModel.is_deleted.is_(False),
                   Annotation.animal_id.isnot(None)))
    if video_id is not None:
        q = q.filter(ImageModel.video_id == video_id)
    rows = q.order_by(Annotation.animal_id,
                      ImageModel.video_id,
                      ImageModel.frame_index).all()

    tracks = defaultdict(list)
    for im, ann in rows:
        aid = int(ann.animal_id)
        cx = ann.x + ann.w / 2
        cy = ann.y + ann.h / 2
        tracks[aid].append({
            "video_id": im.video_id,
            "frame_index": int(im.frame_index) if im.frame_index is not None else None,
            "image_id": int(im.id),
            "timestamp_sec": im.timestamp_sec,
            "filename": im.filename,
            "bbox": {"x": ann.x, "y": ann.y, "w": ann.w, "h": ann.h},
            "center": [round(cx, 5), round(cy, 5)],
            "behavior": ann.behavior,
        })

    proj = db.query(Project).filter(Project.id == project_id).first()
    proj_name = proj.name if proj else "project"

    if fmt == "json":
        payload = {
            "project_id": project_id,
            "project_name": proj_name,
            "exported_at": utcnow().isoformat(),
            "tracks_count": len(tracks),
            "tracks": [
                {
                    "animal_id": aid,
                    "frames_count": len(frames),
                    "frames": frames,
                }
                for aid, frames in sorted(tracks.items())
            ],
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=body, media_type="application/json; charset=utf-8",
            headers={"Content-Disposition":
                     "attachment; filename=tracks_project_%d.json" % project_id})

    buf = StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow([
        "animal_id", "video_id", "frame_index", "image_id",
        "timestamp_sec", "filename",
        "x", "y", "w", "h", "cx", "cy", "behavior",
    ])
    for aid in sorted(tracks.keys()):
        for fr in tracks[aid]:
            ts = "" if fr["timestamp_sec"] is None else "%.3f" % fr["timestamp_sec"]
            w.writerow([
                aid, fr["video_id"] or "",
                fr["frame_index"] if fr["frame_index"] is not None else "",
                fr["image_id"], ts, fr["filename"],
                "%.6f" % fr["bbox"]["x"], "%.6f" % fr["bbox"]["y"],
                "%.6f" % fr["bbox"]["w"], "%.6f" % fr["bbox"]["h"],
                "%.5f" % fr["center"][0], "%.5f" % fr["center"][1],
                fr["behavior"] or "",
            ])
    body = buf.getvalue().encode("utf-8-sig")
    return Response(
        content=body, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 "attachment; filename=tracks_project_%d.csv" % project_id})

# MOVED to routers/ (Stage 3.11): @app.get("/api/keypoint_schema")
def get_keypoint_schema(project_id: Optional[int] = None,
                         db: Session = Depends(get_db)):
    """[FIX:v1341-backend] Возвращает схему для проекта (или дефолт)."""
    from config import get_keypoint_schema_for_project as _gk
    _schema = _gk(db, project_id) if project_id else KEYPOINT_SCHEMA
    return {
        "names": [
            {"name": n, "label_ru": ru, "label_en": en, "parent": p}
            for (n, ru, en, p) in _schema
        ],
        "edges": [[p, n] for (n, _ru, _en, p) in _schema if p],
        "project_id": project_id,
    }

# MOVED to routers/ (Stage 3.11): @app.get("/api/images/{image_id}/keypoints_by_index")
def keypoints_by_index(image_id: int, db: Session = Depends(get_db)):
    """V8.8.6: восстановлен после случайного удаления."""
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound",
                                 "fallback": "Image not found"})
    anns = (db.query(Annotation)
              .filter(Annotation.image_id == image_id)
              .order_by(Annotation.id).all())
    ann_ids = [a.id for a in anns]
    out = {}
    if not ann_ids:
        return out
    kp_rows = (db.query(Keypoint)
                 .filter(Keypoint.annotation_id.in_(ann_ids))
                 .all())
    by_ann = defaultdict(list)
    for kp in kp_rows:
        by_ann[kp.annotation_id].append({
            "name": kp.name, "x": kp.x, "y": kp.y,
            "visibility": kp.visibility,
        })
    for i, a in enumerate(anns):
        out[str(i)] = by_ann.get(a.id, [])
    return out

# ============================================================================
# V10.5.0: умное копирование разметки и скелета из похожего кадра.
# ============================================================================

class SmartCopyIn(BaseModel):
    mode: str = "clone_all"
    # clone_all | fill_empty | replace_skeleton | replace_all

def _copy_kps_transformed(db, t_ann, s_kps, s_box):
    sw = s_box.w or 1e-6
    sh = s_box.h or 1e-6
    for kp in s_kps:
        rel_x = (kp.x - s_box.x) / sw
        rel_y = (kp.y - s_box.y) / sh
        nx = max(0.0, min(1.0, t_ann.x + rel_x * t_ann.w))
        ny = max(0.0, min(1.0, t_ann.y + rel_y * t_ann.h))
        db.add(Keypoint(annotation_id=t_ann.id, name=kp.name,
                        x=nx, y=ny, visibility=kp.visibility))

# MOVED to routers/ (Stage 3.11): @app.post("/api/images/{target_id}/smart_copy_from/{source_id}")
def smart_copy_from(target_id: int, source_id: int,
                    payload: SmartCopyIn,
                    db: Session = Depends(get_db)):
    """Копирование из похожего кадра с матчингом по IoU и центрам."""
    target = db.query(ImageModel).filter(ImageModel.id == target_id).first()
    source = db.query(ImageModel).filter(ImageModel.id == source_id).first()
    if not target or not source:
        raise HTTPException(404, "Image not found")
    if target.project_id != source.project_id:
        raise HTTPException(400, "Изображения из разных проектов")

    s_anns = (db.query(Annotation).filter(Annotation.image_id == source_id).order_by(Annotation.id).all())
    if not s_anns:
        return {"status": "ok", "copied_boxes": 0, "copied_kps": 0, "matched": 0}

    s_ann_ids = [a.id for a in s_anns]
    s_kps = defaultdict(list)
    for kp in db.query(Keypoint).filter(Keypoint.annotation_id.in_(s_ann_ids)).all():
        s_kps[kp.annotation_id].append(kp)

    t_anns = db.query(Annotation).filter(Annotation.image_id == target_id).order_by(Annotation.id).all()

    copied_boxes = 0
    copied_kps = 0
    matched = 0

    if payload.mode == "clone_all" or not t_anns:
        for s in s_anns:
            new_ann = Annotation(image_id=target_id, x=s.x, y=s.y, w=s.w, h=s.h,
                                 label=s.label, confidence=s.confidence,
                                 is_frozen=s.is_frozen, behavior=s.behavior, animal_id=s.animal_id)
            db.add(new_ann)
            db.flush()
            copied_boxes += 1
            kps = s_kps.get(s.id, [])
            for kp in kps:
                db.add(Keypoint(annotation_id=new_ann.id, name=kp.name, x=kp.x, y=kp.y, visibility=kp.visibility))
                copied_kps += 1
    else:
        t_ann_ids = [a.id for a in t_anns]
        t_has_kp = set(r.annotation_id for r in db.query(Keypoint.annotation_id).filter(Keypoint.annotation_id.in_(t_ann_ids)).distinct().all())

        for t in t_anns:
            best = None
            best_iou = 0.0
            best_dist = 999.0
            tcx, tcy = t.x + t.w/2, t.y + t.h/2
            for s in s_anns:
                iou = _iou_xywh({"x": t.x, "y": t.y, "w": t.w, "h": t.h}, {"x": s.x, "y": s.y, "w": s.w, "h": s.h})
                scx, scy = s.x + s.w/2, s.y + s.h/2
                dist = ((tcx-scx)**2 + (tcy-scy)**2)**0.5
                if iou > best_iou or (best is None and dist < best_dist):
                    best_iou = iou
                    best_dist = dist
                    best = s
            # V10.5.1: мягкий матчинг
            if best and (best_iou >= 0.10 or best_dist < 0.15):
                matched += 1
                kps = s_kps.get(best.id, [])

                if payload.mode == "fill_empty" and t.id in t_has_kp:
                    continue

                if payload.mode == "replace_all":
                    t.x, t.y, t.w, t.h = best.x, best.y, best.w, best.h
                    t.animal_id = best.animal_id
                    t.behavior = best.behavior
                    copied_boxes += 1

                if payload.mode in ("replace_skeleton", "replace_all"):
                    db.query(Keypoint).filter(Keypoint.annotation_id == t.id).delete(synchronize_session=False)

                _copy_kps_transformed(db, t, kps, best)
                copied_kps += len(kps)

    db.commit()
    return {"status": "ok", "copied_boxes": copied_boxes, "copied_kps": copied_kps, "matched": matched}

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
# MOVED to routers/ (Stage 3.11): @app.get("/api/settings/trash_ttl")
def get_trash_ttl(db: Session = Depends(get_db)):
    return {"days": get_trash_ttl_days(db)}

class ModelModeIn(BaseModel):
    use_single: bool = True

# MOVED to routers/ (Stage 3.11): @app.get("/api/settings/model_mode")
def get_model_mode(db: Session = Depends(get_db)):
    return {"use_single": _is_single_model_mode(db)}

# MOVED to routers/ (Stage 3.11): @app.post("/api/settings/model_mode")
def set_model_mode(payload: ModelModeIn, db: Session = Depends(get_db)):
    set_setting(db, SETTING_USE_SINGLE_MODEL, "1" if payload.use_single else "0")
    log_status("info", "settings", f"Режим моделей: {'одна' if payload.use_single else 'раздельные'}")
    return {"use_single": payload.use_single}

# MOVED to routers/ (Stage 3.11): @app.post("/api/settings/trash_ttl")
def update_trash_ttl(days: int = Form(...), db: Session = Depends(get_db)):
    days = max(0, min(3650, int(days)))
    set_setting(db, SETTING_TRASH_TTL, days)
    log_status("info", "settings", f"Корзина: автоочистка через {days} дн.")
    return {"days": days}

# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------
# [PATCH:STAGE6-F03-4.1] moved → routers/models.py (@app.get("/api/models"))
# [PATCH:STAGE6-F03-4.1] moved → routers/models.py (@app.get("/api/models/compatibility"))
# [PATCH:STAGE6-F03-4.1] moved → routers/models.py (@app.post("/api/models/activate"))
# [PATCH:STAGE6-F03-4.1] moved → routers/models.py (@app.delete("/api/models/{name}"))
# [STAGE4:MODEL-REVEAL]
# [PATCH:STAGE6-F03-4.1] moved → routers/models.py (@app.post("/api/models/{name}/reveal"))
# [/STAGE4:MODEL-REVEAL]

# [PATCH:STAGE6-F03-4.1] moved → routers/models.py (@app.post("/api/models/{name}/rename"))
# [PATCH:STAGE6-F03-4.1] moved → routers/models.py (@app.get("/api/models/bootstrap/status"))
# [PATCH:STAGE6-F03-4.1] moved → routers/models.py (@app.get("/api/models/bootstrap/events"))
# [PATCH:STAGE6-F03-4.1] moved → routers/models.py (@app.post("/api/models/download"))
# ============================================================================
# [STAGE2:onnx-endpoint] Экспорт активной/указанной модели в ONNX.
# ============================================================================
# [PATCH:STAGE6-F03-4.1] moved → routers/models.py (@app.post("/api/models/{name}/export_onnx"))
# [/STAGE2:onnx-endpoint]

# ---------------------------------------------------------------------------
# SAM
# ---------------------------------------------------------------------------
# SAM routes moved to routers/ml.py

# ---------------------------------------------------------------------------
# Active learning
# ---------------------------------------------------------------------------
def _latest_train_run_for_project(db, project_id: int):
    if not os.path.isdir(RUNS_DIR):
        return None
    candidates = []
    for name in os.listdir(RUNS_DIR):
        if not name.startswith("train_"):
            continue
        meta_path = os.path.join(RUNS_DIR, name, "metadata.json")
        if not os.path.exists(meta_path):
            continue
        try:
            mtime = os.path.getmtime(meta_path)
            meta = _read_run_metadata(RUNS_DIR, name, mtime)
            if meta is None:
                continue
            if int(meta.get("project_id", 0)) == project_id:
                candidates.append((meta.get("created_at", ""), meta))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

# MOVED to routers/ (Stage 3.11): @app.get("/api/projects/{project_id}/active_learning")
def active_learning_state(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    annotated_total = int(
        db.query(func.count(func.distinct(Annotation.image_id)))
          .join(ImageModel, Annotation.image_id == ImageModel.id)
          .filter(ImageModel.project_id == project_id,
                  ImageModel.is_deleted.is_(False))
          .scalar() or 0
    )
    total_images = int(
        db.query(func.count(ImageModel.id))
          .filter(ImageModel.project_id == project_id,
                  ImageModel.is_deleted.is_(False))
          .scalar() or 0
    )
    last = _latest_train_run_for_project(db, project_id)
    if not last:
        return {
            "annotated_total": annotated_total, "total_images": total_images,
            "new_since_train": 0, "last_train": None,
            "show_suggestion": False, "reason": "no_previous_training",
            "threshold": ACTIVE_LEARNING_NEW_THRESHOLD,
        }
    last_count = int(last.get("annotated_count") or 0)
    new_since = max(0, annotated_total - last_count)
    show = new_since >= ACTIVE_LEARNING_NEW_THRESHOLD and annotated_total > last_count
    return {
        "annotated_total": annotated_total, "total_images": total_images,
        "new_since_train": new_since,
        "last_train": {
            "run_id": last.get("run_id"),
            "created_at": last.get("created_at"),
            "model_name": last.get("model_name"),
            "annotated_count": last_count,
            "summary": last.get("summary") or {},
        },
        "show_suggestion": show,
        "reason": "enough_new_annotations" if show else "not_enough_new",
        "threshold": ACTIVE_LEARNING_NEW_THRESHOLD,
    }

# ---------------------------------------------------------------------------
# Training metrics
# ---------------------------------------------------------------------------
# [PATCH:STAGE6-F03-4.2] moved → routers/train.py (@app.get("/api/train/runs"))
# [PATCH:STAGE6-F03-4.2] moved → routers/train.py (@app.get("/api/train/runs/{folder}/metrics"))
# [PATCH:STAGE6-F03-4.2] moved → routers/train.py (@app.get("/api/train/runs/{folder}/file/{name}"))
# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
# [PATCH:STAGE6-F03-4.2] moved → routers/train.py (@app.post("/api/train/start"))
# [PATCH:STAGE6-F03-4.2] moved → routers/train.py (@app.get("/api/train/status"))
# MOVED to routers/ (Stage 3.11): @app.get("/api/projects/{project_id}/skeletons_count")
def skeletons_count(project_id: int, db: Session = Depends(get_db)):
    """V8.7.0: сколько аннотаций проекта имеют скелет."""
    n = _count_annotations_with_skeleton(db, project_id)
    return {"count": n, "min_required": 30}

# [PATCH:STAGE6-F03-4.2] moved → routers/train.py (@app.post("/api/train/stop"))
# [PATCH:STAGE6-F03-4.2] moved → routers/train.py (@app.get("/api/train/events"))
# [PATCH:STAGE6-F03-4.2] moved → routers/train.py (@app.post("/api/train/reset"))
# ---------------------------------------------------------------------------
# Batch autolabel
# ---------------------------------------------------------------------------
# [PATCH:STAGE6-PART2] moved batch_autolabel_start
# [PATCH:STAGE6-PART2] moved batch_autolabel_status
# [PATCH:STAGE6-PART2] moved batch_autolabel_stop
# [PATCH:STAGE6-PART2] moved batch_autolabel_events
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
    # [PATCH:STAGE2:E2-CACHE-INVALIDATION-DELETE-VIDEO] инвалидация кэшей
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
                raise HTTPException(413, f"Видео больше {MAX_VIDEO_MB} МБ")
        except (ValueError, TypeError):
            pass
    fname = file.filename or "video.mp4"
    _, ext = _split_name_ext(fname)
    ext = (ext or "").lower()
    if ext not in VIDEO_EXTS:
        raise HTTPException(400, f"Неподдерживаемый формат: {ext or '—'}")
    try:
        efps = float(extract_fps)
    except (TypeError, ValueError):
        efps = DEFAULT_EXTRACT_FPS
    if efps not in VALID_EXTRACT_FPS:
        raise HTTPException(400, f"extract_fps должен быть одним из: {VALID_EXTRACT_FPS}")
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
                raise HTTPException(413, f"Видео больше {MAX_VIDEO_MB} МБ")
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
        # [STAGE1.3:safe-image-open-video] Decompression bomb кадра
        # → кадр пропускается, сервер не падает с OOM.
        try:
            with open(fp, "rb") as _vf:
                _vdata = _vf.read()
            pil = _open_image_safe(_vdata).convert("RGB")
            _orig_w, _orig_h = pil.size  # [PATCH:STAGE1_VIDEO_ORIG_DIMS]
            pil = letterbox(pil, FIXED_SIZE, LETTERBOX_FILL)
            new_fname = f"{uuid.uuid4().hex}.jpg"
            new_path = os.path.join(UPLOAD_DIR, new_fname)
            pil.save(new_path, "JPEG", quality=85) # [PERF:jpg-85]
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
        # [PATCH:F-16] per-frame commit — previous frames survive errors
        try:
            im = ImageModel(
                project_id=project_id, filename=unique_name, path=new_path,
                width=FIXED_SIZE[0], height=FIXED_SIZE[1],
                is_deleted=False, phash=ph or None, is_hard=False,
                video_id=v.id, frame_index=idx,
                original_width=_orig_w, original_height=_orig_h,  # [PATCH:STAGE1_VIDEO_ORIG_DIMS]
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
    # [PATCH:STAGE3_SIMILAR_STREAM]
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
    # [/PATCH:STAGE3_SIMILAR_STREAM]
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
def copy_annotations(target_id: int, source_id: int, db: Session = Depends(get_db)):  # [PATCH:F-12]
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

def _copy_skeleton_one(db, target_img_id: int, source_img_id: int,
                        iou_min: float = 0.20) -> dict:
    """Копирует keypoints между двумя изображениями с матчингом bbox по IoU.

    Правило:
      * для каждой target-рамки БЕЗ скелета ищем source-рамку с максимальным IoU;
      * если IoU >= iou_min — копируем keypoints с трансформом координат
        относительно source-bbox в target-bbox;
      * уже размеченные target-рамки пропускаем.
    """
    src_anns = (db.query(Annotation)
                  .filter(Annotation.image_id == source_img_id).all())
    dst_anns = (db.query(Annotation)
                  .filter(Annotation.image_id == target_img_id)
                  .order_by(Annotation.id).all())
    if not src_anns or not dst_anns:
        return {"copied": 0, "skipped": 0, "matched_boxes": []}

    src_ids = [a.id for a in src_anns]
    kp_rows = (db.query(Keypoint)
                 .filter(Keypoint.annotation_id.in_(src_ids)).all())
    kps_by_ann = defaultdict(list)
    for kp in kp_rows:
        kps_by_ann[kp.annotation_id].append(kp)
    src_with_kp = [a for a in src_anns if kps_by_ann.get(a.id)]
    if not src_with_kp:
        return {"copied": 0, "skipped": 0, "matched_boxes": []}

    copied = 0
    skipped = 0
    matched = []
    for dst in dst_anns:
        existing = (db.query(Keypoint.id)
                      .filter(Keypoint.annotation_id == dst.id).first())
        if existing:
            skipped += 1
            continue
        # Ищем лучший source по IoU
        best = None
        best_iou = 0.0
        for src in src_with_kp:
            iou = _iou_xywh(
                {"x": dst.x, "y": dst.y, "w": dst.w, "h": dst.h},
                {"x": src.x, "y": src.y, "w": src.w, "h": src.h},
            )
            if iou > best_iou:
                best_iou = iou
                best = src
        if best is None or best_iou < iou_min:
            continue
        # Трансформ: keypoint в координатах source-рамки → в координатах target-рамки.
        sw = best.w or 1e-6
        sh = best.h or 1e-6
        for kp in kps_by_ann[best.id]:
            rel_x = (kp.x - best.x) / sw
            rel_y = (kp.y - best.y) / sh
            new_x = dst.x + rel_x * dst.w
            new_y = dst.y + rel_y * dst.h
            new_x = max(0.0, min(1.0, new_x))
            new_y = max(0.0, min(1.0, new_y))
            db.add(Keypoint(annotation_id=dst.id, name=kp.name,
                            x=new_x, y=new_y, visibility=kp.visibility))
            copied += 1
        matched.append({
            "target_ann_id": dst.id,
            "source_ann_id": best.id,
            "iou": round(best_iou, 3),
            "keypoints": len(kps_by_ann[best.id]),
        })
    if matched:
        db.commit()
    return {"copied_kp": copied, "skipped": skipped,
            "matched_boxes": matched}

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
    # [STAGE1-A:behavior-bbox-relative-call]
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
                "is_target": bool(target_ids) and (cls_id in target_ids),  # [STAGE4:FIX-AUTOLABEL-FALLBACK]
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
# [PATCH:STAGE6-PART2] moved bulk_move
# [PATCH:STAGE6-PART2] moved bulk_copy
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
# [PATCH:REFACTOR-FIX] local _process_dataset_zip removed (source of truth: services/zip_import_service.py)


# [PATCH:REFACTOR-FIX] IMPORT_PROGRESS lives in services/zip_import_service.py



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
    # [STAGE-SEC1]:import_annotations
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
        # [PATCH:REFACTOR-FIX] prevent IMPORT_CANCELS memory leak
        IMPORT_CANCELS.pop(project_id, None)
        _remove_file_safe(tmp_zip)

# ---------------------------------------------------------------------------
# External importers
# ---------------------------------------------------------------------------
# [PATCH:STAGE6-PART2] moved _download_to_file
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
                              cancel_event=None):  # [PATCH:STAGE1-IMPORT-CANCEL]
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
    # [STAGE-SEC1]:import_roboflow
    check_project_access(db, project_id, user)
    # [PATCH:STAGE1-IMPORT-CANCEL-ROBOFLOW]
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
    # [STAGE-SEC1]:import_supervisely
    check_project_access(db, project_id, user)
    # [PATCH:STAGE1-IMPORT-CANCEL-SUPERVISELY]
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
    # [STAGE-SEC1]:import_url
    check_project_access(db, project_id, user)
    _rate_limit(_limiter_import, "url", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
    # [PATCH:STAGE1-IMPORT-CANCEL-URL]
    cancel_event = threading.Event()
    IMPORT_CANCELS[project_id] = cancel_event
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(400, "URL обязателен")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(400, "URL должен начинаться с http(s)://")
    # [STAGE5:ssrf-import-url]
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
                # [PATCH:STAGE1-IMPORT-CANCEL-URL]
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
                    # [PATCH:STAGE1-IMPORT-CANCEL-URL]
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
    # [STAGE-SEC1]:import_local_folder
    check_project_access(db, project_id, user)
    _rate_limit(_limiter_import, "local_folder", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
    # [PATCH:STAGE1_IMPORT_LOCAL_CANCEL] cancel_event был undefined
    cancel_event = threading.Event()  # [PATCH:STAGE1-IMPORT-CANCEL-LOCAL]
    IMPORT_CANCELS[project_id] = cancel_event
    src = (payload.path or "").strip()
    if not src:
        raise HTTPException(400, "Путь обязателен")
    if not os.path.isabs(src):
        raise HTTPException(400, "Путь должен быть абсолютным")
    if not os.path.isdir(src):
        raise HTTPException(404, f"Папка не найдена: {src}")
    # [STAGE5:import-local-restrict]
    _allowed_roots = [
        os.path.realpath(IMPORT_DIR),
        os.path.realpath(UPLOAD_DIR),
    ]
    try:
        from services.settings_service import get_setting as _gs
        _custom_root = _gs(db, "import_root", "")
        if _custom_root:
            # [PATCH:STAGE2-IMPORT-ROOT-GUARD]
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
    # [PATCH:STAGE1:E1-SYMLINK] skip symlinks & enforce containment
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
# [PATCH:STAGE6-PART2] moved _http_get_json
def _http_get_json(url: str, headers: dict, timeout: int = 120,
                    retries: int = 2) -> dict:
    """V7.9.3: retries + backoff. 4xx не retry-им."""
    # [STAGE5:ssrf-http-get]
    if not is_safe_external_url(url):
        raise HTTPException(400, "URL ведёт во внутреннюю сеть (SSRF protection)")
    last_exc = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_exc = e
            if 400 <= e.code < 500 and e.code != 429:
                raise
        except Exception as e:
            last_exc = e
        if attempt < retries:
            delay = 1.5 * (2 ** attempt)
            log.warning("_http_get_json attempt %d failed: %s; retry in %.1fs",
                        attempt + 1, _mask_exc(last_exc), delay)
            time.sleep(delay)
    raise last_exc
# [PATCH:STAGE6-PART2] moved _http_post_json
def _http_post_json(url: str, headers: dict, body: dict, timeout: int = 120,
                     retries: int = 2) -> dict:
    """V7.9.3: retries + backoff. 4xx не retry-им — payload/ключа не поправим."""
    # [STAGE5:ssrf-http-post]
    if not is_safe_external_url(url):
        raise HTTPException(400, "URL ведёт во внутреннюю сеть (SSRF protection)")
    data = json.dumps(body).encode("utf-8")
    hdr = {"Content-Type": "application/json", "User-Agent": "DatasetBuilder/7.9.3"}
    hdr.update(headers or {})
    last_exc = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=hdr, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_exc = e
            if 400 <= e.code < 500 and e.code != 429:
                raise
        except Exception as e:
            last_exc = e
        if attempt < retries:
            delay = 1.5 * (2 ** attempt)
            log.warning("_http_post_json attempt %d failed: %s; retry in %.1fs",
                        attempt + 1, _mask_exc(last_exc), delay)
            time.sleep(delay)
    raise last_exc

@app.post("/api/projects/{project_id}/import/labelbox")
def import_labelbox(project_id: int, payload: ImportLabelboxIn,
                     user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    # [STAGE-SEC1]:import_labelbox
    check_project_access(db, project_id, user)
    _rate_limit(_limiter_import, "labelbox", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
    # [PATCH:STAGE1_IMPORT_LABELBOX_CANCEL] cancel_event был undefined
    cancel_event = threading.Event()  # [PATCH:STAGE1-IMPORT-CANCEL-LABELBOX]
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
    # [STAGE-SEC1]:import_scale
    check_project_access(db, project_id, user)
    # [PATCH:STAGE1-IMPORT-CANCEL-SCALE]
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
    # [STAGE-SEC1]:import_darwin
    check_project_access(db, project_id, user)
    # [PATCH:STAGE1-IMPORT-CANCEL-DARWIN]
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
# [PATCH:STAGE6-PART2] moved backup_project
# [PATCH:STAGE6-PART2] moved download_backup
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
# [/PATCH:STAGE3_ANNS_WITH_KP_CHUNKED]

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
                include_meta: bool = False,  # [PATCH:STAGE1_LETTERBOX_YOLO_SIG]
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
    # [PATCH:STAGE2:E2-EXPORT-ATOMIC-YOLO]
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
        # [STAGE2:dataset-card-export]
        try:
            from services.dataset_card_service import generate_dataset_card
            z.writestr("README.md", generate_dataset_card(db, project_id))
        except Exception:
            pass
        # [STAGE1:dataset-info]
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
        # [FIX:v1341-backend]
        from config import get_keypoint_schema_for_project as _gk
        _export_schema = _gk(db, project_id) if use_pose else KEYPOINT_SCHEMA

        # [PATCH:STAGE3_EXPORT_YOLO_BATCH]
        # [PATCH:STAGE4-C14-N13] Pre-compute iname_map / anns_by_image / kp_by_ann
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
        # [/PATCH:STAGE3_EXPORT_YOLO_BATCH]
        # [/PATCH:STAGE4-C14-N13]
        for bucket_name, bucket_images in buckets.items():
            if not bucket_images:
                continue
            sub_img = f"images/{bucket_name}" if use_split else "images"
            sub_lbl = f"labels/{bucket_name}" if use_split else "labels"
            for img in bucket_images:
                # [PATCH:STAGE2:E2-EXPORT-MISSING-YOLO]
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
        # [PATCH:STAGE1_LETTERBOX_YOLO]
        if include_meta:
            try:
                import json as _json
                _meta = _build_letterbox_meta(images)
                z.writestr("dataset_meta.json",
                           _json.dumps(_meta, ensure_ascii=False, indent=2))
            except Exception:
                log.exception("dataset_meta.json (yolo) failed")
        # [/PATCH:STAGE1_LETTERBOX_YOLO]
    suffix = "orig" if naming == "original" else "num"
    suffix += "_split" if use_split else ""
    _cleanup_old_exports("yolo_project_")
    log_status("info", "export",
               f"Экспорт YOLO проекта #{project_id} (класс «{object_class}»): {len(images)} фото")
    # [STAGE1:WEBHOOK-EXPORT]
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
    # [/STAGE1:WEBHOOK-EXPORT]
    return FileResponse(zip_path, filename=f"yolo_project_{project_id}_{suffix}.zip",
                        media_type="application/zip")

@app.get("/api/projects/{project_id}/export/coco")
def export_coco(project_id: int, naming: str = "numbered", split: str = "none",
                include_meta: bool = False,  # [PATCH:STAGE1_LETTERBOX_COCO]
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
    # [PATCH:STAGE2:E2-EXPORT-ATOMIC-COCO]
    with _atomic_zip(zip_path) as z:
        # V8.6.0: определяем, добавлять ли keypoints в COCO.
        use_kp = _project_has_keypoints(db, project_id)
        _img_ids_all = [im.id for im in images]
        _kps_by_ann = _anns_with_keypoints(db, _img_ids_all) if use_kp else {}
        # [FIX:v1341-backend] кастомная схема
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
                # [PATCH:STAGE2:E2-EXPORT-MISSING-COCO]
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
                        n = len(_export_schema)  # [PATCH:STAGE4-C15-schema-len]
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
        # [PATCH:STAGE1_LETTERBOX_COCO]
        if include_meta:
            try:
                import json as _json
                _meta = _build_letterbox_meta(images)
                z.writestr("dataset_meta.json",
                           _json.dumps(_meta, ensure_ascii=False, indent=2))
            except Exception:
                log.exception("dataset_meta.json (coco) failed")
        # [/PATCH:STAGE1_LETTERBOX_COCO]
    suffix = "orig" if naming == "original" else "num"
    suffix += "_split" if use_split else ""
    _cleanup_old_exports("coco_project_")
    log_status("info", "export",
               f"Экспорт COCO проекта #{project_id} (класс «{object_class}»): {len(images)} фото")
    # [STAGE1:WEBHOOK-EXPORT]
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
    # [/STAGE1:WEBHOOK-EXPORT]
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

# [PATCH:STAGE6-PART2] moved storage_info
# [PATCH:STAGE6-PART2] moved storage_paths
# [PATCH:STAGE6-PART2] moved storage_backup_db
# [PATCH:STAGE6-PART2] moved migrate_status
# [PATCH:STAGE6-PART2] moved migrate_start
# [PATCH:STAGE6-PART2] moved migrate_reset
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
        # [STAGE5:ffmpeg-allowlist]
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
# [PATCH:STAGE6-PART2] moved _backfill_v760
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

    # [STAGE1-A:validator-extensions]
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


# [PATCH:STAGE2_1:track-metrics]
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
# [/PATCH:STAGE2_1:track-metrics]

# [PATCH:STAGE2_2:agtech-csv]
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
# [/PATCH:STAGE2_2:agtech-csv]

# [PATCH:STAGE2_3:rbac-endpoints]
class UserIn(BaseModel):
    username: str
    full_name: str = ""
    password: str = ""
    role: str = "annotator"


# [PATCH:STAGE4_APP_HASH_REMOVED] _hash_password_simple удалён (не использовался).

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
def list_users(db: Session = Depends(get_db)): # [PATCH:STAGE3_USERS_LIST]
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
    # [STAGE3:create-user-real] argon2 + temp password + must_change_password
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
    # [PATCH:FIX_USER_CREATION]
    if payload.password:
        if len(payload.password) < 8:
            raise HTTPException(400, "Пароль должен быть не менее 8 символов")
        temp_pw = payload.password
        generated = False
    else:
        temp_pw = _sec.token_urlsafe(12)
        generated = True
    # [/PATCH:FIX_USER_CREATION]
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
    # [STAGE3:delete-user-real] protect last admin, cascade sessions
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
# [/PATCH:STAGE2_3:rbac-endpoints]

# [PATCH:STAGE3_1:endpoints]
class ValidateBehaviorIn(BaseModel):
    image_id: int
    true_behavior: str
    annotation_id: Optional[int] = None
    validated_by: Optional[str] = None


_VALID_BEHAVIORS = {"eat", "walk", "lie", "drink", "stand", "active"}


# MOVED to routers/ (Stage 3.11): @app.post("/api/projects/{project_id}/validate_behavior")
def validate_behavior(project_id: int, payload: ValidateBehaviorIn,
                      db: Session = Depends(get_db)):
    """[PATCH:STAGE3_1] Compare expert ground truth with auto-label for one image."""
    from models import BehaviorValidation

    norm = (payload.true_behavior or "").strip().lower()
    if norm not in _VALID_BEHAVIORS:
        raise HTTPException(
            400, f"true_behavior must be one of: {sorted(_VALID_BEHAVIORS)}")

    proj = (db.query(Project)
              .filter(Project.id == project_id, Project.is_deleted.is_(False))
              .first())
    if not proj:
        raise HTTPException(404, "Project not found")

    img = (db.query(ImageModel)
             .filter(ImageModel.id == payload.image_id,
                     ImageModel.project_id == project_id,
                     ImageModel.is_deleted.is_(False))
             .first())
    if not img:
        raise HTTPException(404, "Image not found in this project")

    q = db.query(Annotation).filter(Annotation.image_id == img.id)
    if payload.annotation_id is not None:
        q = q.filter(Annotation.id == payload.annotation_id)
    anns = q.order_by(Annotation.id).all()
    if not anns:
        raise HTTPException(404, "No annotations on image")

    details = []
    matched_any = False
    for a in anns:
        auto = (a.behavior or "").strip().lower()
        if not auto:
            continue
        is_match = (auto == norm)
        if is_match:
            matched_any = True
        db.add(BehaviorValidation(
            annotation_id=a.id,
            project_id=project_id,
            auto_behavior=auto,
            true_behavior=norm,
            is_match=1 if is_match else 0,
            validated_at=utcnow(),
            validated_by=payload.validated_by,
        ))
        details.append({
            "annotation_id": a.id,
            "auto_behavior": auto,
            "is_match": is_match,
        })
    if not details:
        raise HTTPException(400, "No annotations with behavior label on this image")

    _db_commit_safe(db)
    log_status("info", "system",
               f"Ground-truth validate: project #{project_id}, "
               f"image #{img.id}, true={norm}, match={matched_any}")

    return {
        "is_match": matched_any,
        "auto_behavior": details[0]["auto_behavior"],
        "true_behavior": norm,
        "matched_count": sum(1 for d in details if d["is_match"]),
        "total": len(details),
        "details": details,
    }


# MOVED to routers/ (Stage 3.11): @app.get("/api/projects/{project_id}/agreement_score")
def agreement_score(project_id: int, db: Session = Depends(get_db)):
    """[PATCH:STAGE3_1] Cohen's kappa between auto-labels and expert labels."""
    from models import BehaviorValidation

    proj = (db.query(Project)
              .filter(Project.id == project_id, Project.is_deleted.is_(False))
              .first())
    if not proj:
        raise HTTPException(404, "Project not found")

    rows = (db.query(BehaviorValidation)
              .filter(BehaviorValidation.project_id == project_id)
              .all())
    n = len(rows)
    if n == 0:
        return {
            "project_id": project_id,
            "total": 0,
            "matches": 0,
            "agreement": None,
            "kappa": None,
            "reason": "no_validations_yet",
        }

    matches = sum(1 for r in rows if int(r.is_match or 0) == 1)
    p_o = matches / n

    classes = set()
    for r in rows:
        if r.auto_behavior:
            classes.add(r.auto_behavior)
        if r.true_behavior:
            classes.add(r.true_behavior)
    auto_counts = {c: 0 for c in classes}
    true_counts = {c: 0 for c in classes}
    for r in rows:
        if r.auto_behavior in auto_counts:
            auto_counts[r.auto_behavior] += 1
        if r.true_behavior in true_counts:
            true_counts[r.true_behavior] += 1

    p_e = sum((auto_counts[c] / n) * (true_counts[c] / n) for c in classes)
    kappa = None
    if p_e < 1.0:
        kappa = (p_o - p_e) / (1.0 - p_e)

    return {
        "project_id": project_id,
        "total": n,
        "matches": matches,
        "agreement": round(p_o, 4),
        "kappa": round(kappa, 4) if kappa is not None else None,
        "by_class": {
            c: {"auto": auto_counts[c], "true": true_counts[c]}
            for c in sorted(classes)
        },
    }
# [/PATCH:STAGE3_1:endpoints]

# [PATCH:STAGE3_2:edge-package-endpoint]
# MOVED to routers/ (Stage 3.11): @app.get("/api/models/{name}/edge_package")
def download_edge_package(name: str, db: Session = Depends(get_db)):
    """[PATCH:STAGE3_2] Build a zip with edge_server.py + Dockerfile + ONNX model."""
    p = _safe_model_path(name)
    if not os.path.exists(p):
        raise HTTPException(404, {"key": "error.modelNotFound",
                                 "fallback": "Model not found"})

    onnx_path = p
    if not p.lower().endswith(".onnx"):
        try:
            from services.train_service import export_to_onnx
            onnx_path = export_to_onnx(p, MODEL_DIR, dynamic=True)
        except Exception as e:
            log.exception("edge_package: onnx export failed")
            raise HTTPException(500, f"ONNX export failed: {_safe_error_message(e)}")
    if not os.path.exists(onnx_path):
        raise HTTPException(500, "ONNX file missing after export")

    edge_dir = os.path.join(BASE_DIR, "edge_runtime")
    edge_server = os.path.join(edge_dir, "edge_server.py")
    dockerfile = os.path.join(edge_dir, "Dockerfile.edge")
    if not os.path.exists(edge_server) or not os.path.exists(dockerfile):
        raise HTTPException(500, "edge_runtime files missing on server")

    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(edge_server, "edge_package/edge_server.py")
            z.write(dockerfile, "edge_package/Dockerfile")
            z.write(onnx_path, "edge_package/model.onnx")
            z.writestr(
                "edge_package/README.md",
                "# DatasetBuilder Edge Runtime\n\n"
                "Build: docker build -f Dockerfile -t db-edge:latest .\n"
                "Run:   docker run --runtime nvidia --network host "
                "-e EDGE_RTSP_URL=rtsp://... db-edge:latest\n"
            )
    except Exception as e:
        log.exception("edge_package: zip build failed")
        raise HTTPException(500, f"Zip build failed: {_safe_error_message(e)}")
    buf.seek(0)

    onnx_name = os.path.basename(onnx_path)
    package_name = f"edge_package_{os.path.splitext(onnx_name)[0]}.zip"
    log_status("info", "export", f"Edge package: {name} -> {onnx_name}")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={package_name}",
            "Cache-Control": "no-store",
        },
    )
# [/PATCH:STAGE3_2:edge-package-endpoint]


# MOVED to routers/ (Stage 3.11): @app.get("/api/projects/{project_id}/versions/diff_extended")
def versions_diff_extended(project_id: int, hash1: str, hash2: str, db: Session = Depends(get_db)):
    from models import DatasetVersion
    v1 = db.query(DatasetVersion).filter(DatasetVersion.project_id == project_id, DatasetVersion.hash == hash1).first()
    if not v1: raise HTTPException(404, "Version 1 not found")

    img_count = db.query(func.count(ImageModel.id)).filter(ImageModel.project_id == project_id, ImageModel.is_deleted == False).scalar() or 0
    ann_count = db.query(func.count(Annotation.id)).join(ImageModel, Annotation.image_id == ImageModel.id).filter(ImageModel.project_id == project_id, ImageModel.is_deleted == False).scalar() or 0
    kp_count = db.query(func.count(Keypoint.id)).join(Annotation, Keypoint.annotation_id == Annotation.id).join(ImageModel, Annotation.image_id == ImageModel.id).filter(ImageModel.project_id == project_id, ImageModel.is_deleted == False).scalar() or 0
    beh_count = db.query(func.count(Annotation.id)).join(ImageModel, Annotation.image_id == ImageModel.id).filter(ImageModel.project_id == project_id, ImageModel.is_deleted == False, Annotation.behavior.isnot(None)).scalar() or 0

    v1_img = v1.image_count
    v1_ann = v1.annotation_count
    # [PATCH:VERSION_DIFF_KP_BEH] [PATCH:FIX_APP_INDENT]
    v1_kp = getattr(v1, 'keypoint_count', 0) or 0
    v1_beh = getattr(v1, 'behavior_count', 0) or 0
    return {
        "images_added": max(0, img_count - v1_img),
        "images_removed": max(0, v1_img - img_count),
        "annotations_added": max(0, ann_count - v1_ann),
        "annotations_removed": max(0, v1_ann - ann_count),
        "keypoints_added": max(0, kp_count - v1_kp),
        "keypoints_removed": max(0, v1_kp - kp_count),
        "behaviors_added": max(0, beh_count - v1_beh),
        "behaviors_removed": max(0, v1_beh - beh_count),
        "is_identical": False
    }


# ══════════════════════════════════════════════════════════════════════════
 # Простая и надежная авторизация
# ══════════════════════════════════════════════════════════════════════════


# ==============================================================================
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

# [STAGE13:app-refactor]

# [FIX:v1341-backend]
