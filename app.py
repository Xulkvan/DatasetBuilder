"""
Dataset Builder — V10.5.7
============================================================
Backend: FastAPI + (MySQL | SQLite) + YOLO + SAM + ffmpeg.
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
import math
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
_SUBPROC_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# CREATE_NEW_PROCESS_GROUP есть только на Windows — на Linux/macOS
# это AttributeError. Берём через getattr с дефолтом 0.
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
import asyncio
import logging
import warnings
import urllib.request
import urllib.error
import uvicorn

import xml.etree.ElementTree as ET

from collections import defaultdict, deque, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from io import StringIO
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Depends, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, Response, JSONResponse
from pydantic import BaseModel, Field, field_validator
from PIL import Image

Image.MAX_IMAGE_PIXELS = 50_000_000

from sqlalchemy import inspect, text, func, case, or_, and_
from sqlalchemy.orm import Session

from database import SessionLocal, Base, engine, get_db, DB_ENGINE, DATABASE_URL, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME


# V13.1.0: восстановленные сервисы

from models import Project, ImageModel, Annotation, Keypoint, Setting, Tag, ImageTag, Video

from schemas import *
from config import *
from config import _ANSI_RE, _EPOCH_RE, _HEX_COLOR_RE, _MODEL_NAME_RE
from logger import log_status, utcnow, STATUS_LOG, STATUS_LOG_LOCK, _sanitize_path

from services.settings_service import get_setting, set_setting, get_trash_ttl_days
from services.behavior_service import _get_stable_center, predict_behavior_from_keypoints, _kp_lookup, _avg_y
from services.ffmpeg_service import (
    _check_ffmpeg, _probe_video, _extract_frames, _ffmpeg_os_info,
    _FFMPEG_PATHS, _FFMPEG_LOCK, _resolve_ffmpeg,
)
from services.bootstrap_service import (
    BOOTSTRAP_STATE, BOOTSTRAP_LOCK, BOOTSTRAP_EVENT, BOOTSTRAP_THREAD,
    _MODEL_ACTIVATION_LOCK,
    _bootstrap_snapshot, _bootstrap_set,
    _yolo_filename, _download_with_progress, _download_model_worker,
    _bootstrap_default_model_if_empty,
)
from services.trash_service import (
    cleanup_expired_trash, _purge_videos, _start_trash_cleaner_thread,
)
from services.train_service import (
    _ann_keypoints_as_list, prepare_training_dataset_pose,
    _save_training_metadata, _summarize_training_results,
)
from services.file_service import (
    _safe_model_path, _sanitize_model_name, _unique_model_name_from_disk, _is_simple_filename,
    sanitize_display_name, validate_user_filename, make_unique_filename, _unique_name_mem,
    _detect_image_format, _open_image_safe, _split_name_ext, letterbox
)
from services.image_service import (
    _remove_file_safe, _remove_thumb, _queue_thumb, ensure_thumb,
    _invalidate_stats_cache, get_project_stats_cached,
    _invalidate_phash_index, find_duplicate,
    _iou_xywh, dedup_boxes,
    phash_hex, _hex_to_int, _hamming_int, hamming_hex,
    _get_duplicate_ids_cached,
    _get_phash_index, _find_duplicates_via_index, _compute_duplicate_ids,
)
from services.rate_limiter import (
    SimpleRateLimiter, _rate_limit,
    _limiter_upload, _limiter_import, _limiter_autolabel, _limiter_train,
)
from services.ml_service import (
    _YOLO_CACHE, get_active_model_path, get_active_pose_model_path,
    _get_yolo_model, _clear_yolo_cache,
    _autolabel_image_predict, _autolabel_batch_predict, _autolabel_image_with_model,
    _save_autolabel, _save_autolabel_no_commit,
    _is_duplicate_box, _load_boxes_xywh, _load_annotations,
    _apply_pose_detection_to_anns, _count_annotations_with_skeleton,
    _read_model_class_names, _resolve_target_class_ids,
    _get_model_classes_cached, _invalidate_model_classes_cache,
    _is_pose_model_name, _is_single_model_mode,
    _find_first_pose_in_dir,
)
from services.sam_service import (
    _SAM_CACHE, get_sam_model_name, _get_sam_model, _clear_sam_cache,
    _bbox_from_mask_np, _extract_sam_result, _run_sam_predict,
)

from logger import (
    log_status, utcnow,
    STATUS_LOG, STATUS_LOG_LOCK, _sanitize_path,
)

# V13.1.1: создаём таблицы после импорта моделей.
# Раньше это было в database.py, но там циклический импорт с models.
Base.metadata.create_all(bind=engine)
print(f"[db] create_all: таблицы проверены/созданы")

log = logging.getLogger("db")

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
    ("annotations", "behavior_source", "VARCHAR(16) NULL"),  # [STAGE1-A:behavior-source-migration]
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
    ("projects", "random_seed", "INT NOT NULL DEFAULT 42"),  # [STAGE2:seed-migration]
    # [FIX:v1341-backend]
    ("projects", "auto_blur_enabled", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("projects", "auto_blur_classes", "TEXT NULL"),
    ("streams", "capture_fps", "FLOAT NOT NULL DEFAULT 1.0"),
    ("projects", "data_retention_days", "INT NOT NULL DEFAULT 0"),  # [PATCH:STAGE1_MIGRATIONS]
    ("images", "original_width",  "INT NULL"),  # [PATCH:STAGE1_MIGRATIONS]
    ("images", "original_height", "INT NULL"),  # [PATCH:STAGE1_MIGRATIONS]
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
                else:
                    conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}"))
            log.info("migrate: %s.%s added", table, column)
        except Exception as e:
            log.warning("migrate: %s.%s skipped (%s)", table, column, e)

ensure_schema()


# ============================================================================
# [STAGE2:keypoint-schema-migration] CREATE TABLE IF NOT EXISTS
# project_keypoint_schemas. Дополняет Base.metadata.create_all для случаев,
# когда модель ProjectKeypointSchema была добавлена после первичной инициализации.
# ============================================================================
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
# [/STAGE2:keypoint-schema-migration]


# ============================================================================
# [STAGE3:stream-migrations] is_stream_frame в images + CREATE TABLE streams.
# ============================================================================
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

# V7.5.0: PyInstaller-friendly пути
if getattr(sys, 'frozen', False):
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))
    DATA_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_ROOT = BASE_DIR

DATA_ROOT = os.getenv("DATA_ROOT", DATA_ROOT)
os.makedirs(DATA_ROOT, exist_ok=True)

UPLOAD_DIR = os.path.join(DATA_ROOT, "uploads")
EXPORT_DIR = os.path.join(DATA_ROOT, "exports")
IMPORT_DIR = os.path.join(DATA_ROOT, "imports")
MODEL_DIR  = os.path.join(DATA_ROOT, "models")
RUNS_DIR   = os.path.join(DATA_ROOT, "runs")
THUMB_DIR  = os.path.join(DATA_ROOT, "thumbs")
BACKUP_DIR = os.path.join(DATA_ROOT, "backups")
VIDEO_DIR  = os.path.join(DATA_ROOT, "videos")
DATA_DIR   = os.path.join(DATA_ROOT, "data")

INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")
STYLE_CSS_PATH = os.path.join(BASE_DIR, "style.css")
APP_JS_PATH = os.path.join(BASE_DIR, "app.js")
I18N_JS_PATH = os.path.join(BASE_DIR, "i18n.js")

FIXED_SIZE = (640, 640)
LETTERBOX_FILL = (114, 114, 114)
THUMB_SIZE = (64, 64)
CONF_THRESHOLD = 0.25
DEDUP_IOU_THRESHOLD = 0.5
PHASH_DUPLICATE_THRESHOLD = 6
SIMILAR_DEFAULT_THRESHOLD = 12

DEFAULT_TRASH_TTL_DAYS = 30
SETTING_TRASH_TTL = "trash_ttl_days"
SETTING_ACTIVE_MODEL = "active_model"
SETTING_ACTIVE_POSE_MODEL = "active_pose_model"
SETTING_USE_SINGLE_MODEL = "use_single_model"
SETTING_SAM_MODEL = "sam_model_name"
SETTING_DEFAULT_EXTRACT_FPS = "default_extract_fps"
SETTING_BACKFILL_DONE = "backfill_v760_done"
SETTING_FFMPEG_PATH = "ffmpeg_path"  # V7.6.2

DEFAULT_SAM_MODEL = "mobile_sam.pt"
VALID_SAM_MODELS = ("mobile_sam.pt", "sam2_t.pt", "sam2_s.pt", "sam2_b.pt", "FastSAM-s.pt")
SAM_MIN_POINTS = 1
SAM_MAX_POINTS = 8
ACTIVE_LEARNING_NEW_THRESHOLD = 30

# V8.5.0: provisional схема скелета (17 точек).
# Легко заменить под требования заказчика — только этот блок.
KEYPOINT_SCHEMA = [
    # name,          label_ru,    label_en,    parent_name (или None)
    ("nose",         "Нос",       "Nose",       None),
    ("head_top",     "Макушка",   "Head top",   "nose"),
    ("ear_L",        "Ухо Л",     "Ear L",      "head_top"),
    ("ear_R",        "Ухо П",     "Ear R",      "head_top"),
    ("neck",         "Шея",       "Neck",       "head_top"),
    ("withers",      "Холка",     "Withers",    "neck"),
    ("mid_spine",    "Спина",     "Mid spine",  "withers"),
    ("hip",          "Таз",       "Hip",        "mid_spine"),
    ("tail_base",    "Хвост",     "Tail base",  "hip"),
    ("knee_FL",      "Колено ПЛ", "Knee FL",    "withers"),
    ("hoof_FL",      "Копыто ПЛ", "Hoof FL",    "knee_FL"),
    ("knee_FR",      "Колено ПП", "Knee FR",    "withers"),
    ("hoof_FR",      "Копыто ПП", "Hoof FR",    "knee_FR"),
    ("hock_RL",      "Скак. ЗЛ",  "Hock RL",    "hip"),
    ("hoof_RL",      "Копыто ЗЛ", "Hoof RL",    "hock_RL"),
    ("hock_RR",      "Скак. ЗП",  "Hock RR",    "hip"),
    ("hoof_RR",      "Копыто ЗП", "Hoof RR",    "hock_RR"),
]
KEYPOINT_NAMES = tuple(k[0] for k in KEYPOINT_SCHEMA)
KEYPOINT_VALID = frozenset(KEYPOINT_NAMES)

DEFAULT_OBJECT_CLASS = "pig"
MAX_OBJECT_CLASS_LEN = 128

# V8.3.0: допустимые значения поведения животного.
BEHAVIORS = ("eat", "walk", "lie", "drink", "stand", "active")
MAX_ANIMAL_ID = 999999

def _norm_behavior(b):
    """V8.3.0: нормализация значения behavior."""
    if b is None:
        return None
    s = str(b).strip().lower()
    return s if s in BEHAVIORS else None

def _norm_animal_id(v):
    """V8.3.0: номер животного — положительный int или None."""
    if v is None or v == "":
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if n <= 0 or n > MAX_ANIMAL_ID:
        return None
    return n

VALID_THUMB_SIZES = (32, 48, 64, 96)
VALID_DEFAULT_ZOOMS = (None, 1.0, 1.5, 2.0, 3.0, 4.0)

VIDEO_EXTS = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"})
VALID_EXTRACT_FPS = (0.5, 1.0, 2.0, 5.0, 10.0)
DEFAULT_EXTRACT_FPS = 2.0
MAX_VIDEO_MB = int(os.getenv("MAX_VIDEO_MB", "2048"))
MAX_VIDEO_BYTES = MAX_VIDEO_MB * 1024 * 1024
MAX_VIDEO_FRAMES = int(os.getenv("MAX_VIDEO_FRAMES", "3000"))

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_IMPORT_MB = int(os.getenv("MAX_IMPORT_MB", "2048"))
MAX_IMPORT_BYTES = MAX_IMPORT_MB * 1024 * 1024
MAX_EXTRACTED_MB = int(os.getenv("MAX_EXTRACTED_MB", "10240"))
MAX_EXTRACTED_BYTES = MAX_EXTRACTED_MB * 1024 * 1024

MAX_EPOCHS = 500
MAX_EPOCH_PLAUSIBLE = 10000
MAX_TRAIN_LOG_LINES = 300
MAX_FREEZE_LAYERS = 9

BATCH_IMPORT_CHUNK = 100
BATCH_AUTOLABEL_COMMIT_EVERY = 20

MIN_BOX_AREA = 0.005
MAX_OVERLAP_IOU = 0.9
NESTED_RATIO = 0.9
MAX_ASPECT = 5.0

# File name helpers moved to services/file_service.py

def _is_image_ext(name: str) -> bool:
    _, ext = _split_name_ext(name)
    return ext.lower() in IMAGE_EXTS

# ---------------------------------------------------------------------------
# Определение формата картинок
# ---------------------------------------------------------------------------
# File magic & open helpers moved to services/file_service.py

# ---------------------------------------------------------------------------
# Безопасная распаковка zip
# ---------------------------------------------------------------------------
def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: str):
    target_root = os.path.realpath(target_dir)
    total_extracted = 0
    for member in zf.infolist():
        name = member.filename
        if not name or name in ('.', '..'):
            continue
        if name.startswith('/') or name.startswith('\\'):
            raise HTTPException(400, f"Абсолютный путь в архиве: {name}")
        if re.match(r'^[A-Za-z]:', name):
            raise HTTPException(400, f"Windows-абсолютный путь в архиве: {name}")
        if '\x00' in name:
            raise HTTPException(400, "NUL в имени файла")
        target = os.path.realpath(os.path.join(target_dir, name))
        if not (target == target_root or target.startswith(target_root + os.sep)):
            raise HTTPException(400, f"Опасный путь в архиве: {name}")
        mode = (member.external_attr >> 16) & 0xFFFF
        if mode and (mode & 0xF000) in (0xA000, 0x6000, 0x2000):
            log.warning("skip non-regular file in zip: %s", name)
            continue
        total_extracted += member.file_size
        if total_extracted > MAX_EXTRACTED_BYTES:
            raise HTTPException(413, f"Распакованный архив превышает {MAX_EXTRACTED_MB} МБ")
        if member.compress_size > 0 and member.file_size > 10 * 1024 * 1024:
            ratio = member.file_size / member.compress_size
            if ratio > 1000:
                raise HTTPException(400, f"Подозрительная компрессия (ratio={ratio:.0f}): {name}")
        if member.is_dir():
            os.makedirs(target, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)

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

def _collect_image_files(root_dir: str):
    out = []
    for root, dirs, files in os.walk(root_dir):
        for f in files:
            if _is_image_ext(f):
                out.append(os.path.join(root, f))
    return out

# ---------------------------------------------------------------------------
# Converters к COCO
# ---------------------------------------------------------------------------
def _labelbox_to_coco(items: list, project_name: str) -> dict:
    coco = {"images": [], "annotations": [], "categories": []}
    cat_map = {}
    next_cat = 1
    next_ann = 1
    next_img = 1
    for item in items:
        data_row = item.get("data_row") or {}
        gkey = data_row.get("global_key") or data_row.get("external_id") or ""
        if not gkey:
            continue
        media_attrs = data_row.get("media_attributes") or {}
        w = int(media_attrs.get("width") or 0)
        h = int(media_attrs.get("height") or 0)
        img_id = next_img
        next_img += 1
        coco["images"].append({"id": img_id, "file_name": gkey, "width": w, "height": h})
        projects = item.get("projects") or {}
        for pid, proj in projects.items():
            labels = proj.get("labels") or []
            for label in labels:
                anns = label.get("annotations") or {}
                objects = anns.get("objects") or []
                for obj in objects:
                    name = (obj.get("name") or "object").strip()
                    if name not in cat_map:
                        cat_map[name] = next_cat
                        coco["categories"].append({"id": next_cat, "name": name})
                        next_cat += 1
                    cid = cat_map[name]
                    bbox = obj.get("bounding_box") or {}
                    if bbox:
                        left = float(bbox.get("left") or 0)
                        top = float(bbox.get("top") or 0)
                        bw = float(bbox.get("width") or 0)
                        bh = float(bbox.get("height") or 0)
                    else:
                        poly = (obj.get("polygon") or [])
                        if not poly:
                            continue
                        xs = [float(p.get("x") or 0) for p in poly]
                        ys = [float(p.get("y") or 0) for p in poly]
                        left, top = min(xs), min(ys)
                        bw, bh = max(xs) - left, max(ys) - top
                    if bw <= 0 or bh <= 0:
                        continue
                    coco["annotations"].append({
                        "id": next_ann, "image_id": img_id, "category_id": cid,
                        "bbox": [left, top, bw, bh], "area": bw * bh, "iscrowd": 0,
                    })
                    next_ann += 1
    return coco

def _scale_to_coco(items: list) -> dict:
    coco = {"images": [], "annotations": [], "categories": []}
    cat_map = {}
    next_cat = 1
    next_ann = 1
    next_img = 1
    for it in items:
        ref = it.get("reference_id") or it.get("external_id") or it.get("id") or ""
        img_id = next_img
        next_img += 1
        coco["images"].append({
            "id": img_id, "file_name": ref,
            "width": int(it.get("width") or 0), "height": int(it.get("height") or 0),
        })
        for ann in (it.get("annotations") or []):
            label = (ann.get("label") or ann.get("annotation_label") or "object").strip()
            if label not in cat_map:
                cat_map[label] = next_cat
                coco["categories"].append({"id": next_cat, "name": label})
                next_cat += 1
            cid = cat_map[label]
            geom = ann.get("geometry") or {}
            if geom.get("type") == "box" or ("x" in geom and "width" in geom):
                left = float(geom.get("x") or 0)
                top = float(geom.get("y") or 0)
                bw = float(geom.get("width") or 0)
                bh = float(geom.get("height") or 0)
            elif isinstance(geom.get("vertices"), list):
                xs = [float(v.get("x") or 0) for v in geom["vertices"]]
                ys = [float(v.get("y") or 0) for v in geom["vertices"]]
                if not xs or not ys:
                    continue
                left, top = min(xs), min(ys)
                bw, bh = max(xs) - left, max(ys) - top
            else:
                continue
            if bw <= 0 or bh <= 0:
                continue
            coco["annotations"].append({
                "id": next_ann, "image_id": img_id, "category_id": cid,
                "bbox": [left, top, bw, bh], "area": bw * bh, "iscrowd": 0,
            })
            next_ann += 1
    return coco

def _coco_to_zip(coco: dict, image_urls: dict, out_path: str) -> dict:
    downloaded = 0
    missing = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_annotations.coco.json", json.dumps(coco, ensure_ascii=False, indent=2))
        for im in coco["images"]:
            fname = im["file_name"]
            url = image_urls.get(fname)
            if not url:
                missing.append(fname)
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "DatasetBuilder/7.8.0"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                z.writestr(fname, data)
                downloaded += 1
            except Exception:
                log.exception("download failed for %s", fname)
                missing.append(fname)
    return {"downloaded": downloaded, "missing": missing}

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
# Rate limiter moved to services/rate_limiter.py


def _safe_error_message(e: Exception, context: str = "") -> str:
    name = type(e).__name__
    if "OperationalError" in name or "IntegrityError" in name or "ProgrammingError" in name:
        return f"{context}: ошибка БД" if context else "Ошибка БД"
    msg = str(e)
    msg = re.sub(r'/[^\s]+/', '/…/', msg)
    msg = msg[:200]
    return f"{context}: {msg}" if context else msg

# ---------------------------------------------------------------------------
# Обучение
# ---------------------------------------------------------------------------
# Обучение
# ---------------------------------------------------------------------------
TRAIN_STATE = {
    "status": "idle", "progress": 0.0, "current_epoch": 0, "total_epochs": 0,
    "message": "", "log_lines": [], "model_name": None,
    "project_id": None, "started_at": None, "finished_at": None, "run_id": None,
}
TRAIN_LOCK = threading.Lock()
TRAIN_PROCESS = None
TRAIN_EVENT = threading.Event()

def _train_reset():
    with TRAIN_LOCK:
        TRAIN_STATE.update({
            "status": "idle", "progress": 0.0,
            "current_epoch": 0, "total_epochs": 0,
            "message": "", "log_lines": [], "model_name": None,
            "project_id": None, "started_at": None, "finished_at": None, "run_id": None,
        })
    TRAIN_EVENT.set()

def _train_snapshot():
    with TRAIN_LOCK:
        return dict(TRAIN_STATE)

def prepare_training_dataset(db, project_id: int, run_dir: str) -> str:
    project = db.query(Project).filter(Project.id == project_id).first()
    object_class = (project.object_class if project else DEFAULT_OBJECT_CLASS) or DEFAULT_OBJECT_CLASS
    class_yaml = object_class.replace("'", "''")
    dataset_dir = os.path.join(run_dir, "dataset")
    images_dir = os.path.join(dataset_dir, "images")
    labels_dir = os.path.join(dataset_dir, "labels")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(labels_dir, exist_ok=True)

    all_imgs = (db.query(ImageModel)
                  .filter(ImageModel.project_id == project_id,
                          ImageModel.is_deleted.is_(False)).all())
    pairs = []
    for im in all_imgs:
        anns = db.query(Annotation).filter(Annotation.image_id == im.id).all()
        if not anns:
            continue
        pairs.append((im, anns))
    if not pairs:
        raise RuntimeError("В проекте нет ни одного размеченного изображения")
    if len(pairs) < 10:
        log.warning("ВНИМАНИЕ: всего %d размеченных — обучение может быть нестабильным", len(pairs))

    rng = random.Random(42)
    rng.shuffle(pairs)
    n_val = max(1, int(round(len(pairs) * 0.15))) if len(pairs) >= 7 else 0
    val_pairs = pairs[:n_val]
    train_pairs = pairs[n_val:]
    if not train_pairs:
        train_pairs = pairs
        val_pairs = []

    def _dump(subset, sub_name):
        img_sub = os.path.join(images_dir, sub_name) if sub_name else images_dir
        lbl_sub = os.path.join(labels_dir, sub_name) if sub_name else labels_dir
        os.makedirs(img_sub, exist_ok=True)
        os.makedirs(lbl_sub, exist_ok=True)
        for im, anns in subset:
            dst = os.path.join(img_sub, f"{im.id}.jpg")
            try:
                shutil.copy(im.path, dst)
            except OSError:
                continue
            lines = [f"0 {a.x:.6f} {a.y:.6f} {a.w:.6f} {a.h:.6f}" for a in anns]
            with open(os.path.join(lbl_sub, f"{im.id}.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

    _dump(train_pairs, "train")
    _dump(val_pairs, "val")

    yaml_path = os.path.join(dataset_dir, "data.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        if val_pairs:
            f.write(f"path: {dataset_dir}\n"
                    f"train: images/train\n"
                    f"val: images/val\n"
                    f"nc: 1\n"
                    f"names: ['{class_yaml}']\n")
        else:
            log.warning("val-набор пуст, использую train как val")
            f.write(f"path: {dataset_dir}\n"
                    f"train: images/train\n"
                    f"val: images/train\n"
                    f"nc: 1\n"
                    f"names: ['{class_yaml}']\n")

    log.info("датасет: %d train / %d val (всего размечено %d из %d), класс: %r",
             len(train_pairs), len(val_pairs), len(pairs), len(all_imgs), object_class)
    return yaml_path

def _handle_train_line(line: str):
    with TRAIN_LOCK:
        TRAIN_STATE["log_lines"].append(line)
        if len(TRAIN_STATE["log_lines"]) > MAX_TRAIN_LOG_LINES:
            TRAIN_STATE["log_lines"] = TRAIN_STATE["log_lines"][-MAX_TRAIN_LOG_LINES:]
        m = _EPOCH_RE.match(line)
        if m:
            try:
                cur = int(m.group(1))
                total = int(m.group(2))
            except (ValueError, TypeError):
                cur, total = 0, 0
            if 0 < cur <= total <= MAX_EPOCH_PLAUSIBLE:
                TRAIN_STATE["current_epoch"] = cur
                TRAIN_STATE["total_epochs"] = total
                TRAIN_STATE["progress"] = round(cur / total * 100, 1)
    TRAIN_EVENT.set()

# [FIX:training-reader]
def _read_stream_and_parse(proc, on_line, idle_timeout: float = 2.0):
    """Читаем stdout по байтам, чтобы ловить прогресс-бар tqdm (\r)."""
    def _reader():
        buffer = bytearray()
        try:
            while True:
                chunk = proc.stdout.read(1024)
                if not chunk:
                    break
                buffer.extend(chunk)
                while b'\n' in buffer or b'\r' in buffer:
                    idx_n = buffer.find(b'\n')
                    idx_r = buffer.find(b'\r')
                    if idx_n == -1: idx = idx_r
                    elif idx_r == -1: idx = idx_n
                    else: idx = min(idx_n, idx_r)

                    line_bytes = buffer[:idx]
                    buffer = buffer[idx+1:]
                    while buffer.startswith(b'\n') or buffer.startswith(b'\r'):
                        buffer = buffer[1:]

                    text = line_bytes.decode('utf-8', errors='replace').rstrip()
                    line = _ANSI_RE.sub('', text).strip()
                    if line:
                        on_line(line)
            if buffer:
                text = buffer.decode('utf-8', errors='replace').rstrip()
                line = _ANSI_RE.sub('', text).strip()
                if line:
                    on_line(line)
        except Exception:
            log.exception("read stream error")

    t = threading.Thread(target=_reader, daemon=True, name="train-reader")
    t.start()
    return t

def _train_env():
    env = dict(os.environ)
    for k in ("DB_PASSWORD", "DB_USER", "DB_HOST", "DB_PORT", "DB_NAME"):
        env.pop(k, None)
    env["PYTHONUNBUFFERED"] = "1"
    return env

def _run_training_thread(args, run_dir, run_id, custom_name):
    global TRAIN_PROCESS

    # [FIX:heartbeat] Если YOLO молчит > 15 сек, пишем в лог, что живы
    def _heartbeat():
        last_len = 0
        last_time = time.time()
        while True:
            time.sleep(5)
            with TRAIN_LOCK:
                status = TRAIN_STATE["status"]
                cur_len = len(TRAIN_STATE["log_lines"])
            if status not in ("running", "stopping"):
                break
            if cur_len > last_len:
                last_len = cur_len
                last_time = time.time()
            elif time.time() - last_time > 15:
                _handle_train_line("[train] ⏳ Ожидание вывода от YOLO (сканирование/кэширование датасета)...")
                last_time = time.time()

    try:
        _handle_train_line("[train] 🚀 Запуск процесса обучения...")
        _handle_train_line("[train] ⏳ Если вы используете CPU, сканирование датасета может занять 5-10 минут.")
        log.info("Starting training subprocess: %s", args)
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
            cwd=BASE_DIR,
            env=_train_env(),
            creationflags=_SUBPROC_FLAGS | _CREATE_NEW_PROCESS_GROUP,
            # V7.9.3: POSIX — новая сессия, чтобы SIGINT/SIGTERM
            # на process group добивали DataLoader-воркеры ultralytics.
            start_new_session=(os.name != "nt"),
        )
        with TRAIN_LOCK:
            TRAIN_PROCESS = proc
        threading.Thread(target=_heartbeat, daemon=True).start() # [FIX:heartbeat]
        reader = _read_stream_and_parse(proc, _handle_train_line)
        ret = proc.wait()
        try:
            reader.join(timeout=2.0)
        except Exception:
            pass
        with TRAIN_LOCK:
            status = TRAIN_STATE["status"]
        if status == "stopping":
            last_pt = os.path.join(run_dir, "output", "train", "weights", "last.pt")
            saved_name = None
            if os.path.exists(last_pt):
                try:
                    stem = (custom_name[:-3] if custom_name.lower().endswith(".pt")
                            else custom_name) if custom_name else f"train_{run_id}"
                    partial_name = f"{stem}_partial.pt"
                    partial_name = _unique_model_name_from_disk(partial_name)
                    shutil.copy(last_pt, os.path.join(MODEL_DIR, partial_name))
                    saved_name = partial_name
                    try:
                        with _MODEL_ACTIVATION_LOCK:
                            db3 = SessionLocal()
                            try:
                                _task = TRAIN_STATE.get("task") or "detect"
                                if _task == "pose" and not _is_pose_model_name(partial_name):
                                    _stem = partial_name[:-3] if partial_name.lower().endswith(".pt") else partial_name
                                    partial_name = f"{_stem}-pose.pt"
                                    partial_name = _unique_model_name_from_disk(partial_name)
                                    shutil.copy(last_pt, os.path.join(MODEL_DIR, partial_name))
                                    saved_name = partial_name
                                if _is_single_model_mode(db3) or _task == "detect":
                                    set_setting(db3, SETTING_ACTIVE_MODEL, partial_name)
                                else:
                                    set_setting(db3, SETTING_ACTIVE_POSE_MODEL, partial_name)
                            finally:
                                db3.close()
                            _clear_yolo_cache()
                            _invalidate_model_classes_cache()
                    except Exception:
                        log.exception("activate partial model failed")
                    try:
                        db_meta = SessionLocal()
                        try:
                            proj_id = TRAIN_STATE.get("project_id")
                            proj = db_meta.query(Project).filter(Project.id == proj_id).first() if proj_id else None
                            object_class = (proj.object_class if proj else DEFAULT_OBJECT_CLASS) or DEFAULT_OBJECT_CLASS
                            annotated_count = 0
                            if proj_id:
                                annotated_count = int(
                                    db_meta.query(func.count(func.distinct(Annotation.image_id)))
                                        .join(ImageModel, Annotation.image_id == ImageModel.id)
                                        .filter(ImageModel.project_id == proj_id,
                                                ImageModel.is_deleted.is_(False))
                                        .scalar() or 0
                                )
                            _save_training_metadata(
                                run_dir=run_dir, project_id=proj_id or 0,
                                object_class=object_class,
                                model_name=partial_name,
                                epochs=int(TRAIN_STATE.get("total_epochs") or 0),
                                imgsz=640, annotated_count=annotated_count,
                            )
                        finally:
                            db_meta.close()
                    except Exception:
                        log.exception("save partial metadata failed")
                except Exception:
                    log.exception("save last.pt as model failed")
            with TRAIN_LOCK:
                TRAIN_STATE["status"] = "stopped"
                TRAIN_STATE["message"] = (
                    f"Остановлено. Модель сохранена: {saved_name}" if saved_name
                    else "Остановлено. last.pt не найден."
                )
                if saved_name:
                    TRAIN_STATE["model_name"] = saved_name
            log_status("warning", "train",
                       f"Обучение остановлено пользователем, last.pt → {saved_name or 'нет'}")
        elif ret == 0:
            best = os.path.join(run_dir, "output", "train", "weights", "best.pt")
            if os.path.exists(best):
                if custom_name:
                    new_name = _unique_model_name_from_disk(custom_name)
                else:
                    new_name = _unique_model_name_from_disk(f"train_{run_id}.pt")
                _task = TRAIN_STATE.get("task") or "detect"
                if _task == "pose" and not _is_pose_model_name(new_name):
                    _stem = new_name[:-3] if new_name.lower().endswith(".pt") else new_name
                    new_name = f"{_stem}-pose.pt"
                    new_name = _unique_model_name_from_disk(new_name)
                shutil.copy(best, os.path.join(MODEL_DIR, new_name))
                try:
                    with _MODEL_ACTIVATION_LOCK:
                        db2 = SessionLocal()
                        try:
                            if _is_single_model_mode(db2) or _task == "detect":
                                set_setting(db2, SETTING_ACTIVE_MODEL, new_name)
                            else:
                                set_setting(db2, SETTING_ACTIVE_POSE_MODEL, new_name)
                        finally:
                            db2.close()
                        _clear_yolo_cache()
                        _invalidate_model_classes_cache()
                except Exception:
                    log.exception("activate trained model %s failed", new_name)

                try:
                    db_meta = SessionLocal()
                    try:
                        proj_id = TRAIN_STATE.get("project_id")
                        proj = db_meta.query(Project).filter(Project.id == proj_id).first() if proj_id else None
                        object_class = (proj.object_class if proj else DEFAULT_OBJECT_CLASS) or DEFAULT_OBJECT_CLASS
                        annotated_count = 0
                        if proj_id:
                            annotated_count = int(
                                db_meta.query(func.count(func.distinct(Annotation.image_id)))
                                    .join(ImageModel, Annotation.image_id == ImageModel.id)
                                    .filter(ImageModel.project_id == proj_id,
                                            ImageModel.is_deleted.is_(False))
                                    .scalar() or 0
                            )
                        _save_training_metadata(
                            run_dir=run_dir, project_id=proj_id or 0,
                            object_class=object_class,
                            model_name=new_name,
                            epochs=int(TRAIN_STATE.get("total_epochs") or 0),
                            imgsz=640, annotated_count=annotated_count,
                        )
                    finally:
                        db_meta.close()
                except Exception:
                    log.exception("save training metadata (outer) failed")

                with TRAIN_LOCK:
                    TRAIN_STATE["status"] = "done"
                    TRAIN_STATE["progress"] = 100.0
                    TRAIN_STATE["current_epoch"] = TRAIN_STATE["total_epochs"]
                    TRAIN_STATE["message"] = "Обучение завершено (модель активна)"
                    TRAIN_STATE["model_name"] = new_name
                log_status("success", "train", f"Обучение завершено: {new_name}")
                # [STAGE1:webhook-train-completed]
                try:
                    from services.webhook_service import dispatch_event as _wh_dispatch
                    _wh_dispatch(None, int(TRAIN_STATE.get("project_id") or 0),
                                 "training.completed",
                                 {"model": new_name, "run_id": run_id})
                except Exception:
                    pass
            else:
                with TRAIN_LOCK:
                    TRAIN_STATE["status"] = "error"
                    TRAIN_STATE["message"] = "best.pt не найден после обучения"
                log_status("error", "train", "best.pt не найден после обучения")
        else:
            with TRAIN_LOCK:
                TRAIN_STATE["status"] = "error"
                TRAIN_STATE["message"] = f"Процесс завершился с кодом {ret}"
            log_status("error", "train", f"Обучение упало: код {ret}")
    except Exception as e:
        log.exception("training failed")
        log_status("error", "train", f"Ошибка обучения: {e}")
        with TRAIN_LOCK:
            TRAIN_STATE["status"] = "error"
            TRAIN_STATE["message"] = str(e)
    finally:
        # V11.8.3: cleanup dataset
        try:
            shutil.rmtree(os.path.join(run_dir, "dataset"), ignore_errors=True)
        except Exception:
            pass
        with TRAIN_LOCK:
            TRAIN_STATE["finished_at"] = utcnow().isoformat()
            TRAIN_PROCESS = None
        TRAIN_EVENT.set()

# ---------------------------------------------------------------------------
# Батч-авторазметка
# ---------------------------------------------------------------------------
BATCH_STATE = {
    "status": "idle", "total": 0, "done": 0, "failed": 0,
    "current_id": None, "current_filename": "", "message": "",
    "started_at": None, "finished_at": None, "project_id": None,
    "added": 0, "skipped": 0, "mode": "add",  # V8.2.0
}
BATCH_LOCK = threading.Lock()
BATCH_STOP = threading.Event()
BATCH_THREAD = None
BATCH_EVENT = threading.Event()

def _batch_snapshot():
    with BATCH_LOCK:
        return dict(BATCH_STATE)

def _batch_worker(image_ids, model_path, project_id, mode="add", tta=False):
    global BATCH_THREAD
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            with BATCH_LOCK:
                BATCH_STATE["status"] = "error"
                BATCH_STATE["message"] = "Проект не найден"
            log_status("error", "autolabel", "Батч: проект не найден")
            BATCH_EVENT.set()
            return
        target_label = project.object_class or DEFAULT_OBJECT_CLASS
        try:
            # V13.3.3: Принудительно создаем НОВЫЙ экземпляр модели для фонового потока,
            # чтобы избежать состояния гонки с основным потоком (YOLO не потокобезопасна).
            from ultralytics import YOLO
            model = YOLO(model_path)
            print(f"[BATCH DEBUG] Loaded isolated model: {model_path}")
        except Exception as e:
            with BATCH_LOCK:
                BATCH_STATE["status"] = "error"
                BATCH_STATE["message"] = f"Модель не загружена: {e}"
            log_status("error", "autolabel", f"Батч: модель не загружена: {e}")
            BATCH_EVENT.set()
            return
        target_ids = _resolve_target_class_ids(model, target_label)
        if not target_ids:
            msg = (f"Класс «{target_label}» не поддерживается активной моделью. "
                   f"Выбери OIV7 или обучи свою.")
            with BATCH_LOCK:
                BATCH_STATE["status"] = "error"
                BATCH_STATE["message"] = msg
            log_status("error", "autolabel", f"Батч: {msg}")
            BATCH_EVENT.set()
            return
        total = len(image_ids)
        with BATCH_LOCK:
            BATCH_STATE["total"] = total
            BATCH_STATE["added"] = 0
            BATCH_STATE["skipped"] = 0
            BATCH_STATE["mode"] = _norm_mode(mode)
        log_status("info", "autolabel",
                   f"Батч-авторазметка (V13 Batch Engine): {total} изобр., класс «{target_label}»")
        BATCH_EVENT.set()

        # Определяем размер батча: на GPU больше, на CPU меньше
        batch_size = 16
        try:
            import torch
            if not torch.cuda.is_available():
                batch_size = 4  # На CPU маленькие батчи, чтобы не забить RAM
        except Exception:
            batch_size = 4

        for chunk_start in range(0, total, batch_size):
            if BATCH_STOP.is_set():
                db.rollback()
                with BATCH_LOCK:
                    BATCH_STATE["status"] = "stopped"
                    BATCH_STATE["message"] = "Остановлено пользователем"
                log_status("warning", "autolabel", "Батч-авторазметка остановлена")
                BATCH_EVENT.set()
                return

            chunk_ids = image_ids[chunk_start:chunk_start+batch_size]
            imgs = db.query(ImageModel).filter(ImageModel.id.in_(chunk_ids)).all()
            if not imgs:
                with BATCH_LOCK:
                    BATCH_STATE["done"] += len(chunk_ids)
                    BATCH_STATE["failed"] += len(chunk_ids)
                BATCH_EVENT.set()
                continue

            # Собираем пути для батч-инференса
            valid_imgs = []
            paths = []
            for img in imgs:
                if img and os.path.exists(img.path):
                    valid_imgs.append(img)
                    paths.append(img.path)
                else:
                    with BATCH_LOCK:
                        BATCH_STATE["done"] += 1
                        BATCH_STATE["failed"] += 1
                    BATCH_EVENT.set()

            if not paths:
                continue

            with BATCH_LOCK:
                BATCH_STATE["current_id"] = valid_imgs[0].id
                BATCH_STATE["current_filename"] = f"{valid_imgs[0].filename} (+{len(paths)-1})"
            BATCH_EVENT.set()

            try:
                # Запускаем батч
                W_list = [img.width or 640 for img in valid_imgs]
                H_list = [img.height or 640 for img in valid_imgs]
                batch_results = _autolabel_batch_predict(paths, model, W_list, H_list, target_ids, target_label, tta=tta)

                chunk_added = 0
                chunk_skipped = 0
                for img, raw_new in zip(valid_imgs, batch_results):
                    iid = img.id
                    if _norm_mode(mode) == "add":
                        existing = _load_boxes_xywh(db, iid)
                        unique, skipped_n = [], 0
                        for d in raw_new:
                            if any(_is_duplicate_box(d, e) for e in existing):
                                skipped_n += 1
                            else:
                                unique.append(d)
                        for a in unique:
                            db.add(Annotation(
                                image_id=iid, x=a["x"], y=a["y"],
                                w=a["w"], h=a["h"], label=target_label,
                                confidence=a["confidence"], is_frozen=False,
                            ))
                        chunk_added += len(unique)
                        chunk_skipped += skipped_n
                    else:
                        _save_autolabel_no_commit(db, iid, raw_new, target_label)
                        chunk_added += len(raw_new)

                # Сначала коммитим в БД, и только потом обновляем UI
                _db_commit_safe(db)

                with BATCH_LOCK:
                    BATCH_STATE["added"] += chunk_added
                    BATCH_STATE["skipped"] += chunk_skipped
                    BATCH_STATE["done"] += len(valid_imgs)
            except Exception as e:
                import traceback
                traceback.print_exc()
                log.warning("batch chunk fail: %s", e)
                db.rollback()
                with BATCH_LOCK:
                    BATCH_STATE["done"] += len(valid_imgs)
                    BATCH_STATE["failed"] += len(valid_imgs)
            BATCH_EVENT.set()

        with BATCH_LOCK:
            BATCH_STATE["status"] = "done"
            BATCH_STATE["message"] = "Готово"
            BATCH_STATE["current_id"] = None
            BATCH_STATE["current_filename"] = ""
        log_status("success", "autolabel",
                   f"Батч-авторазметка завершена: "
                   f"{BATCH_STATE['done'] - BATCH_STATE['failed']} ok, "
                   f"{BATCH_STATE['failed']} ошибок")
    finally:
        db.close()
        with BATCH_LOCK:
            BATCH_STATE["finished_at"] = utcnow().isoformat()
            BATCH_THREAD = None
        BATCH_EVENT.set()
        _invalidate_stats_cache(project_id)
        gc.collect()

# ---------------------------------------------------------------------------
# Migration state (MySQL → SQLite)
# ---------------------------------------------------------------------------
MIGRATE_STATE = {
    "status": "idle", "stage": "", "message": "", "progress": 0.0,
    "stats": {}, "target_path": "", "env_updated": False,
    "started_at": None, "finished_at": None, "error": None,
}
MIGRATE_LOCK = threading.Lock()
MIGRATE_THREAD = None

def _env_file_path() -> str:
    p1 = os.path.join(DATA_ROOT, ".env")
    if os.path.exists(p1):
        return p1
    p2 = os.path.join(BASE_DIR, ".env")
    if os.path.exists(p2):
        return p2
    return p1

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
        except Exception as e:
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

def _cleanup_old_runs():
    """V12.5.0: Удаляет папки обучения старше 30 дней, оставляя 5 последних."""
    try:
        if not os.path.isdir(RUNS_DIR): return
        runs = []
        for name in os.listdir(RUNS_DIR):
            path = os.path.join(RUNS_DIR, name)
            if os.path.isdir(path) and name.startswith("train_"):
                runs.append((path, os.path.getmtime(path)))
        runs.sort(key=lambda x: x[1], reverse=True)
        cutoff = time.time() - 30 * 86400
        deleted = 0
        for path, mtime in runs[5:]:
            if mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                deleted += 1
        if deleted:
            log.info("Cleanup: удалено %d старых папок обучения", deleted)
    except Exception as e:
        log.warning("cleanup old runs failed: %s", e)

def _scan_broken_files():
    """V8.3.1: раз в запуск проверяет наличие файлов на диске."""
    try:
        db = SessionLocal()
        try:
            total = 0
            broken = 0
            for r in db.query(ImageModel.id, ImageModel.path).filter(
                    ImageModel.is_deleted.is_(False)).yield_per(2000):
                total += 1
                if not r.path or not os.path.exists(r.path):
                    broken += 1
            if broken:
                log.warning("startup scan: %d битых файлов из %d (см. "
                            "/api/projects/{id}/broken_images)", broken, total)
            else:
                log.info("startup scan: все %d файлов на месте", total)
        finally:
            db.close()
    except Exception:
        log.exception("scan broken files failed")

# [FIX:v1341-backend]
def _restore_active_streams():
    """Перезапускает воркеры для всех Stream(is_active=True)."""
    try:
        from services.stream_service import start_stream_worker
        from models import Stream
        db = SessionLocal()
        try:
            rows = (db.query(Stream)
                      .filter(Stream.is_active.is_(True)).all())
            for s in rows:
                try:
                    start_stream_worker(
                        s.url, s.project_id,
                        fps=float(getattr(s, "capture_fps", 1.0) or 1.0),
                        stream_id=s.id)
                    log.info("stream restored: id=%d url=%s", s.id, s.url)
                except Exception as e:
                    log.warning("stream restore failed id=%d: %s", s.id, e)
        finally:
            db.close()
    except Exception:
        log.exception("restore active streams failed")


def _warm_yolo_cache():
    """V7.9.3: предзагрузка активной YOLO-модели в фоне при старте.

    Без этого первый запрос /api/object_classes или
    /api/models/compatibility блокируется на 1–3 сек (import
    ultralytics + чтение .pt).
    """
    try:
        db = SessionLocal()
        try:
            path = get_active_model_path(db)
        finally:
            db.close()
        if path:
            _get_yolo_model(path)
            log.info("YOLO warmup: %s", os.path.basename(path))
    except Exception:
        log.exception("YOLO warmup failed")

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        n = cleanup_expired_trash(db)
        if n:
            log.info("Удалено устаревших объектов из корзины: %d", n)
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
    _start_trash_cleaner_thread()
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
    log_status("info", "system", f"Dataset Builder {APP_VERSION} запущен")
    yield
    # V8.1.0: корректно завершаем пул миниатюр.
    try:
        from services.image_service import shutdown_thumb_pool
        shutdown_thumb_pool()
    except Exception:
        log.exception("thumb pool shutdown failed")
    log_status("info", "system", "Приложение останавливается")


def _db_commit_safe(db):
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning("DB commit failed: %s", e)
        raise

# [STAGE1:openapi-config]
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

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:8]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response

# [STAGE2:api-key-middleware]
@app.middleware("http")
async def _v2_api_key_guard(request: Request, call_next):
    """Bearer-токен для /api/v2/* если API_KEY задан."""
    path = request.url.path
    if path.startswith("/api/v2/"):
        expected = (os.getenv("API_KEY") or "").strip()
        if expected:
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Bearer ") or auth[7:].strip() != expected:
                return JSONResponse(status_code=401,
                                    content={"detail": "API key required"})
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

@app.get("/app.js")
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

@app.post("/api/videos/{video_id}/track")
def video_track_start(video_id: int, db: Session = Depends(get_db)):
    """Запускает ByteTrack-трекинг по кадрам видео."""
    global TRACK_THREAD
    with TRACK_LOCK:
        if TRACK_STATE["status"] == "running":
            raise HTTPException(409, "Трекинг уже идёт")
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

@app.get("/api/projects/{project_id}/tracks")
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

@app.post("/api/images/{image_id}/link_from_prev")
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

@app.get("/api/projects/{project_id}/navigate_with_aid")
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


def _check_motion(db, image_id: int, animal_id: int, max_frames_back: int = 10):
    from services.behavior_service import _get_stable_center
    try:
        aid = int(animal_id)
    except (TypeError, ValueError):
        return None
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img or img.video_id is None or img.frame_index is None:
        return None
    cur_ann = db.query(Annotation).filter(Annotation.image_id == image_id, Annotation.animal_id == aid).first()
    if not cur_ann:
        return None
    cur_center, cur_type = _get_stable_center(cur_ann, db.query(Keypoint).filter(Keypoint.annotation_id == cur_ann.id).all())

    prev = (db.query(ImageModel, Annotation)
              .join(Annotation, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.video_id == img.video_id, ImageModel.is_deleted.is_(False), ImageModel.frame_index < img.frame_index, ImageModel.frame_index >= img.frame_index - max_frames_back, Annotation.animal_id == aid)
              .order_by(ImageModel.frame_index.desc()).first())
    if not prev:
        return None
    prev_img, prev_ann = prev
    prev_center, prev_type = _get_stable_center(prev_ann, db.query(Keypoint).filter(Keypoint.annotation_id == prev_ann.id).all())

    dx = cur_center[0] - prev_center[0]
    dy = cur_center[1] - prev_center[1]
    delta = (dx * dx + dy * dy) ** 0.5
    return {"delta": float(delta), "from": prev_center, "to": cur_center, "frame_gap": int(img.frame_index - prev_img.frame_index), "center_source": "keypoints" if cur_type == "keypoints" and prev_type == "keypoints" else "bbox"}

def _check_motion_batch(db, image_id: int):
    """Векторы движения. Ищет совпадения по animal_id до 10 кадров назад."""
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img or img.video_id is None or img.frame_index is None:
        return {}
    cur_anns = db.query(Annotation).filter(Annotation.image_id == image_id).order_by(Annotation.id).all()
    if not cur_anns: return {}

    prev_imgs = (db.query(ImageModel)
                   .filter(ImageModel.video_id == img.video_id,
                           ImageModel.is_deleted.is_(False),
                           ImageModel.frame_index < img.frame_index)
                   .order_by(ImageModel.frame_index.desc())
                   .limit(2).all())

    prev_by_aid = {}
    prev_anns_map = {}
    for pi in prev_imgs:
        anns = db.query(Annotation).filter(Annotation.image_id == pi.id).all()
        prev_anns_map[pi.frame_index] = anns
        for a in anns:
            if a.animal_id is not None:
                aid = int(a.animal_id)
                if aid not in prev_by_aid:
                    prev_by_aid[aid] = (a, pi.frame_index)

    cur_kps_map = defaultdict(list)
    for k in db.query(Keypoint).filter(Keypoint.annotation_id.in_([a.id for a in cur_anns])).all():
        cur_kps_map[k.annotation_id].append(k)

    prev_kps_map = defaultdict(list)
    all_prev_ids = [a.id for pi in prev_imgs for a in prev_anns_map.get(pi.frame_index, [])]
    if all_prev_ids:
        for k in db.query(Keypoint).filter(Keypoint.annotation_id.in_(all_prev_ids)).all():
            prev_kps_map[k.annotation_id].append(k)

    out = {}
    for i, a in enumerate(cur_anns):
        if a.animal_id is None: continue
        aid = int(a.animal_id)
        cur_center, cur_type = _get_stable_center(a, cur_kps_map.get(a.id, []))

        prev_match, prev_src, prev_idx = None, None, None

        if aid in prev_by_aid:
            prev_match, prev_idx = prev_by_aid[aid]
            prev_src = "aid"
        elif prev_imgs:
            imm_prev_idx = prev_imgs[0].frame_index
            for p in prev_anns_map.get(imm_prev_idx, []):
                if p.animal_id is not None and p.animal_id != aid: continue
                iou = _iou_xywh({"x": a.x, "y": a.y, "w": a.w, "h": a.h},
                                {"x": p.x, "y": p.y, "w": p.w, "h": p.h})
                if iou >= 0.10:
                    prev_match, prev_idx, prev_src = p, imm_prev_idx, "iou"
                    break

        if prev_match is None:
            out[str(i)] = {"found": False, "reason": "no_prev_match" if prev_imgs else "no_prev_frame"}
            continue

        prev_center, prev_type = _get_stable_center(prev_match, prev_kps_map.get(prev_match.id, []))
        match_type = "keypoints" if (cur_type == "keypoints" and prev_type == "keypoints") else "bbox"

        dx = cur_center[0] - prev_center[0]
        dy = cur_center[1] - prev_center[1]
        delta = (dx * dx + dy * dy) ** 0.5

        frame_gap = int(img.frame_index - prev_idx)
        if frame_gap > 2:
            out[str(i)] = {"found": False, "reason": "gap_too_large"}
            continue

        out[str(i)] = {
            "found": True,
            "delta": float(delta),
            "from": prev_center,
            "to": cur_center,
            "frame_gap": frame_gap,
            "match_source": prev_src,
            "center_source": match_type,
            "prev_animal_id": int(prev_match.animal_id) if prev_match.animal_id is not None else None,
            "prev_frame_index": int(prev_idx),
        }
    return out

def _check_motion_ex(db, image_id: int, animal_id):
    """V8.8.5: расширенная версия _check_motion с reason, если не найдено.

    Возвращает dict:
      {"found": True,  "delta": float, "from": [...], "to": [...], "frame_gap": int}
      {"found": False, "reason": "..."}
    """
    try:
        aid = int(animal_id)
    except (TypeError, ValueError):
        return {"found": False, "reason": "bad_animal_id"}
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        return {"found": False, "reason": "no_image"}
    if img.video_id is None or img.frame_index is None:
        return {"found": False, "reason": "no_video"}
    cur_ann = (db.query(Annotation)
                 .filter(Annotation.image_id == image_id,
                         Annotation.animal_id == aid)
                 .first())
    if not cur_ann:
        return {"found": False, "reason": "no_current_ann"}
    cur_cx = cur_ann.x + cur_ann.w / 2
    cur_cy = cur_ann.y + cur_ann.h / 2

    # Ищем предыдущий кадр с той же animal_id
    prev = (db.query(ImageModel, Annotation)
              .join(Annotation, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.video_id == img.video_id,
                      ImageModel.is_deleted.is_(False),
                      ImageModel.frame_index < img.frame_index,
                      Annotation.animal_id == aid)
              .order_by(ImageModel.frame_index.desc())
              .first())
    match_source = "aid"

    if not prev:
        # IoU fallback — ищем любую рамку на предыдущем кадре
        prev_frame_any = (db.query(ImageModel)
                            .filter(ImageModel.video_id == img.video_id,
                                    ImageModel.is_deleted.is_(False),
                                    ImageModel.frame_index < img.frame_index)
                            .order_by(ImageModel.frame_index.desc())
                            .first())
        if not prev_frame_any:
            return {"found": False, "reason": "no_prev_frame"}
        cands = (db.query(Annotation)
                   .filter(Annotation.image_id == prev_frame_any.id).all())
        if not cands:
            return {"found": False, "reason": "no_prev_boxes"}
        best_ann = None
        best_iou = 0.0
        for c in cands:
            iou = _iou_xywh(
                {"x": cur_ann.x, "y": cur_ann.y,
                 "w": cur_ann.w, "h": cur_ann.h},
                {"x": c.x, "y": c.y, "w": c.w, "h": c.h},
            )
            if iou > best_iou:
                best_iou = iou
                best_ann = c
        if best_ann is None or best_iou < 0.30:
            return {"found": False,
                    "reason": "no_iou_match (best_iou=%.2f)" % best_iou,
                    "best_iou": round(best_iou, 3)}
        prev = (prev_frame_any, best_ann)
        match_source = "iou"
        prev_img_iou, prev_ann_iou = prev
    prev_img, prev_ann = prev
    prev_cx = prev_ann.x + prev_ann.w / 2
    prev_cy = prev_ann.y + prev_ann.h / 2
    dx = cur_cx - prev_cx
    dy = cur_cy - prev_cy
    delta = (dx * dx + dy * dy) ** 0.5
    return {
        "found": True,
        "delta": float(delta),
        "from": [round(prev_cx, 5), round(prev_cy, 5)],
        "to": [round(cur_cx, 5), round(cur_cy, 5)],
        "frame_gap": int(img.frame_index - prev_img.frame_index),
        "match_source": match_source,
        "prev_animal_id": int(prev_ann.animal_id) if prev_ann.animal_id is not None else None,
    }

@app.get("/api/images/{image_id}/motion_vectors")
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

@app.get("/api/projects/{project_id}/tracks/{animal_id}/frames")
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

@app.get("/api/projects/{project_id}/tracks/export")
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

@app.get("/api/keypoint_schema")
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

@app.get("/api/images/{image_id}/keypoints_by_index")
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

@app.post("/api/images/{target_id}/smart_copy_from/{source_id}")
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
@app.get("/api/settings/trash_ttl")
def get_trash_ttl(db: Session = Depends(get_db)):
    return {"days": get_trash_ttl_days(db)}

class ModelModeIn(BaseModel):
    use_single: bool = True

@app.get("/api/settings/model_mode")
def get_model_mode(db: Session = Depends(get_db)):
    return {"use_single": _is_single_model_mode(db)}

@app.post("/api/settings/model_mode")
def set_model_mode(payload: ModelModeIn, db: Session = Depends(get_db)):
    set_setting(db, SETTING_USE_SINGLE_MODEL, "1" if payload.use_single else "0")
    log_status("info", "settings", f"Режим моделей: {'одна' if payload.use_single else 'раздельные'}")
    return {"use_single": payload.use_single}

@app.post("/api/settings/trash_ttl")
def update_trash_ttl(days: int = Form(...), db: Session = Depends(get_db)):
    days = max(0, min(3650, int(days)))
    set_setting(db, SETTING_TRASH_TTL, days)
    log_status("info", "settings", f"Корзина: автоочистка через {days} дн.")
    return {"days": days}

# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------
@app.get("/api/models")
def list_models(db: Session = Depends(get_db)):
    result = []
    if os.path.isdir(MODEL_DIR):
        # [STAGE3:ONNX-APP]
        for f in sorted(os.listdir(MODEL_DIR)):
            if not (f.endswith(".pt") or f.endswith(".onnx")):
                continue
            p = os.path.join(MODEL_DIR, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            result.append({
                "name": f, "size": st.st_size,
                "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            })
    active = get_setting(db, SETTING_ACTIVE_MODEL, "")
    if not active and result:
        names = [x["name"] for x in result]
        active = "pig.pt" if "pig.pt" in names else names[0]
    return {
        "models": result, "active": active,
        "active_detect": active if not _is_pose_model_name(active) else "",
        "active_pose": get_setting(db, SETTING_ACTIVE_POSE_MODEL, ""),
        "use_single": _is_single_model_mode(db),
    }

@app.get("/api/models/compatibility")
def models_compatibility(object_class: str, db: Session = Depends(get_db)):
    obj = (object_class or "").strip().lower()
    if not obj:
        raise HTTPException(400, "object_class обязателен")
    names = []
    if os.path.isdir(MODEL_DIR):
        names = sorted([f for f in os.listdir(MODEL_DIR)
                        if f.endswith((".pt", ".onnx"))])
    out = {}
    for m in names:
        classes = _get_model_classes_cached(m)
        if classes is None:
            out[m] = {"compatible": None, "reason": "cannot_load", "classes_count": 0}
        else:
            out[m] = {
                "compatible": obj in classes,
                "reason": "ok" if obj in classes else "no_class",
                "classes_count": len(classes),
            }
    return out

@app.post("/api/models/activate")
def activate_model(name: str = Form(...), kind: str = Form("auto"), db: Session = Depends(get_db)):
    with _MODEL_ACTIVATION_LOCK:
        p = _safe_model_path(name)
        if not os.path.exists(p):
            raise HTTPException(404, {"key": "error.modelNotFound", "fallback": "Модель не найдена"})
        single = _is_single_model_mode(db)
        if kind == "auto":
            kind = "pose" if _is_pose_model_name(name) else "detect"
        if single or kind == "detect":
            set_setting(db, SETTING_ACTIVE_MODEL, name)
        else:
            set_setting(db, SETTING_ACTIVE_POSE_MODEL, name)
        _clear_yolo_cache()
        _invalidate_model_classes_cache()
    log_status("info", "model", f"Активная модель ({kind}): {name}")
    return {"active": name, "kind": kind}

@app.delete("/api/models/{name}")
def delete_model(name: str, db: Session = Depends(get_db)):
    p = _safe_model_path(name)
    if not os.path.exists(p):
        raise HTTPException(404, {"key": "error.modelNotFound", "fallback": "Модель не найдена"})
    if os.path.islink(p):
        raise HTTPException(400, {"key": "error.symlinkNotAllowed", "fallback": "Символические ссылки не удаляются"})
    active_detect = get_setting(db, SETTING_ACTIVE_MODEL, "")
    active_pose = get_setting(db, SETTING_ACTIVE_POSE_MODEL, "")
    single = _is_single_model_mode(db)
    if (single and active_detect == name) or (not single and (active_detect == name or active_pose == name)):
        raise HTTPException(400, {"key": "error.modelActive", "fallback": "Это активная модель. Сначала переключись на другую."})
    pt_files = [f for f in os.listdir(MODEL_DIR)
                if f.endswith((".pt", ".onnx"))]
    if len(pt_files) <= 1:
        raise HTTPException(400, {"key": "error.lastModel", "fallback": "Это последняя модель в папке."})
    try:
        os.remove(p)
    except OSError as e:
        raise HTTPException(500, f"Не удалось удалить: {e}")
    _YOLO_CACHE.clear()
    _invalidate_model_classes_cache(name)
    log_status("warning", "model", f"Модель удалена: {name}")
    return {"status": "ok"}



# [STAGE4:MODEL-REVEAL]
@app.post("/api/models/{name}/reveal")
def reveal_model(name: str, db: Session = Depends(get_db)):
    p = _safe_model_path(name)
    if not os.path.exists(p):
        raise HTTPException(404, "Модель не найдена")
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", p])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(p)])
    return {"status": "ok"}
# [/STAGE4:MODEL-REVEAL]

@app.post("/api/models/{name}/rename")
def rename_model(name: str, new_name: str = Form(...), db: Session = Depends(get_db)):
    old_path = _safe_model_path(name)
    if not os.path.exists(old_path):
        raise HTTPException(404, {"key": "error.modelNotFound", "fallback": "Модель не найдена"})
    clean = _sanitize_model_name(new_name)
    if not clean:
        raise HTTPException(400, "Некорректное имя (латиница, цифры, _ - . ( ) и пробел)")
    if clean == name:
        return {"name": name, "old": name}
    case_only = (clean.lower() == name.lower() and clean != name)
    if case_only:
        tmp_name = f"._case_tmp_{uuid.uuid4().hex[:8]}.pt"
        tmp_path = os.path.join(MODEL_DIR, tmp_name)
        new_path = os.path.join(MODEL_DIR, clean)
        try:
            os.rename(old_path, tmp_path)
            os.rename(tmp_path, new_path)
        except OSError as e:
            try:
                if os.path.exists(tmp_path) and not os.path.exists(old_path):
                    os.rename(tmp_path, old_path)
            except OSError:
                log.exception("rollback rename failed for %s", name)
            raise HTTPException(500, f"Не удалось переименовать: {e}")
    else:
        clean = _unique_model_name_from_disk(clean)
        new_path = os.path.join(MODEL_DIR, clean)
        if not os.path.realpath(new_path).startswith(os.path.realpath(MODEL_DIR) + os.sep):
            raise HTTPException(400, {"key": "error.invalidPath", "fallback": "Некорректный путь"})
        try:
            os.rename(old_path, new_path)
        except OSError as e:
            raise HTTPException(500, f"Не удалось переименовать: {e}")
    if get_setting(db, SETTING_ACTIVE_MODEL, "") == name:
        set_setting(db, SETTING_ACTIVE_MODEL, clean)
    if get_setting(db, SETTING_ACTIVE_POSE_MODEL, "") == name:
        set_setting(db, SETTING_ACTIVE_POSE_MODEL, clean)
    _YOLO_CACHE.clear()
    _invalidate_model_classes_cache(old_path)
    _invalidate_model_classes_cache(clean)
    log_status("info", "model", f"Модель переименована: {name} → {clean}")
    return {"name": clean, "old": name}

@app.get("/api/models/bootstrap/status")
def bootstrap_status():
    return _bootstrap_snapshot()

@app.get("/api/models/bootstrap/events")
async def bootstrap_events():
    async def gen():
        snap = _bootstrap_snapshot()
        yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
        last = json.dumps(snap, ensure_ascii=False)
        if snap["status"] != "downloading":
            return
        while True:
            await asyncio.get_event_loop().run_in_executor(None, BOOTSTRAP_EVENT.wait, 1.0)
            BOOTSTRAP_EVENT.clear()
            snap = _bootstrap_snapshot()
            payload = json.dumps(snap, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if snap["status"] != "downloading":
                break
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/models/download")
def download_model(payload: DownloadModelIn, db: Session = Depends(get_db)):
    global BOOTSTRAP_THREAD
    size = payload.size if payload.size in ("n", "s", "m", "l", "x") else "n"
    pretrain = payload.pretrain if payload.pretrain in ("coco", "oiv7") else "oiv7"
    family = payload.family if payload.family in ("v8", "v11", "v26") else "v8"
    task = payload.task if payload.task in ("detect", "pose") else "detect"
    custom_name = payload.custom_name or ""
    if custom_name:
        clean = _sanitize_model_name(custom_name)
        if not clean:
            raise HTTPException(400, "Некорректное имя (латиница, цифры, _ - . ( ) и пробел)")
    with BOOTSTRAP_LOCK:
        if BOOTSTRAP_STATE["status"] == "downloading":
            raise HTTPException(409, "Уже идёт скачивание модели")
        BOOTSTRAP_STATE["status"] = "downloading"
        BOOTSTRAP_STATE["message"] = "Инициализация…"
        BOOTSTRAP_STATE["progress"] = 0.0
        BOOTSTRAP_STATE["filename"] = ""
        BOOTSTRAP_STATE["started_at"] = utcnow().isoformat()
        BOOTSTRAP_STATE["finished_at"] = None
    BOOTSTRAP_EVENT.set()
    t = threading.Thread(target=_download_model_worker,
                         args=(size, pretrain, custom_name, True, family, task),
                         daemon=True, name="model-downloader")
    with BOOTSTRAP_LOCK:
        BOOTSTRAP_THREAD = t
    t.start()
    return {"status": "started", "size": size, "pretrain": pretrain}

# ============================================================================
# [STAGE2:onnx-endpoint] Экспорт активной/указанной модели в ONNX.
# ============================================================================
@app.post("/api/models/{name}/export_onnx")
def export_model_onnx(name: str, dynamic: bool = Form(True),
                      db: Session = Depends(get_db)):
    from services.train_service import export_to_onnx
    p = _safe_model_path(name)
    if not os.path.exists(p):
        raise HTTPException(404, {"key": "error.modelNotFound",
                                 "fallback": "Model not found"})
    try:
        out = export_to_onnx(p, MODEL_DIR, dynamic=bool(dynamic))
    except Exception as e:
        log.exception("export_onnx failed")
        raise HTTPException(500, f"ONNX export failed: {_safe_error_message(e)}")
    log_status("success", "model",
               f"ONNX export: {name} -> {os.path.basename(out)}")
    return {"status": "ok", "model": name,
            "onnx_path": out,
            "onnx_name": os.path.basename(out),
            "size": os.path.getsize(out) if os.path.exists(out) else 0}
# [/STAGE2:onnx-endpoint]

# ---------------------------------------------------------------------------
# SAM
# ---------------------------------------------------------------------------
# SAM routes moved to routers/ml.py

@app.post("/api/images/{image_id}/sam_predict")
def sam_predict(image_id: int, payload: SamPredictIn, db: Session = Depends(get_db)):
    _rate_limit(_limiter_autolabel, "sam", "Слишком много SAM-запросов. Подожди минуту.")
    pts = payload.points or []
    if len(pts) < SAM_MIN_POINTS:
        raise HTTPException(400, "Нужна хотя бы одна точка")
    if len(pts) > SAM_MAX_POINTS:
        raise HTTPException(400, f"Максимум {SAM_MAX_POINTS} точек")
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    name = get_sam_model_name(db)
    try:
        model = _get_sam_model(name)
    except ImportError:
        raise HTTPException(501, "ultralytics не установлен — SAM недоступен")
    except Exception as e:
        raise HTTPException(500, f"SAM не загружен: {_safe_error_message(e)}")
    W = img.width or 640
    H = img.height or 640
    points_px = [[float(p.x) * W, float(p.y) * H] for p in pts]
    labels = [1 if p.positive else 0 for p in pts]
    try:
        res = _run_sam_predict(model, img.path, points_px, labels)
    except Exception as e:
        log.exception("SAM predict failed")
        raise HTTPException(500, f"SAM predict: {_safe_error_message(e)}")
    if not res:
        return {"found": False}
    x1, y1, x2, y2 = res["bbox_px"]
    bbox = {
        "x": max(0.0, min(1.0, x1 / W)),
        "y": max(0.0, min(1.0, y1 / H)),
        "w": max(0.0, min(1.0, (x2 - x1) / W)),
        "h": max(0.0, min(1.0, (y2 - y1) / H)),
    }
    return {"found": True, "bbox": bbox, "score": res["score"],
            "mask": res["mask_b64"], "model": name}

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

@app.get("/api/projects/{project_id}/active_learning")
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
@lru_cache(maxsize=64)
def _read_run_metadata(runs_dir: str, folder: str, mtime: float) -> Optional[dict]:
    """V7.9.0: кэш metadata.json по mtime. Параметр mtime не используется в теле —
    он часть ключа кэша и инвалидируется при изменении файла на диске."""
    path = os.path.join(runs_dir, folder, "metadata.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _list_train_runs(project_id: Optional[int] = None):
    if not os.path.isdir(RUNS_DIR):
        return []
    out = []
    for name in os.listdir(RUNS_DIR):
        if not name.startswith("train_"):
            continue
        run_dir = os.path.join(RUNS_DIR, name)
        if not os.path.isdir(run_dir):
            continue
        meta = None
        meta_path = os.path.join(run_dir, "metadata.json")
        if os.path.exists(meta_path):
            try:
                mtime = os.path.getmtime(meta_path)
                meta = _read_run_metadata(RUNS_DIR, name, mtime)
            except OSError:
                meta = None
        if meta is None:
            meta = {"run_id": name.replace("train_", ""), "project_id": None,
                    "created_at": None, "model_name": None, "summary": {}}
        if project_id is not None and int(meta.get("project_id") or 0) != project_id:
            continue
        tdir = os.path.join(run_dir, "output", "train")
        out.append({
            "run_id": meta.get("run_id") or name.replace("train_", ""),
            "folder": name,
            "project_id": meta.get("project_id"),
            "created_at": meta.get("created_at"),
            "object_class": meta.get("object_class"),
            "model_name": meta.get("model_name"),
            "annotated_count": meta.get("annotated_count"),
            "epochs": meta.get("epochs"),
            "summary": meta.get("summary") or {},
            "has_confusion_matrix": os.path.exists(os.path.join(tdir, "confusion_matrix.png")),
            "has_val_pred": os.path.exists(os.path.join(tdir, "val_batch0_pred.jpg")),
            "has_results_csv": os.path.exists(os.path.join(tdir, "results.csv")),
        })
    out.sort(key=lambda x: (x.get("created_at") or ""), reverse=True)
    return out

@app.get("/api/train/runs")
def train_runs_list(project_id: Optional[int] = None):
    return {"items": _list_train_runs(project_id)}

@app.get("/api/train/runs/{folder}/metrics")
def train_run_metrics(folder: str):
    if not _is_simple_filename(folder):
        raise HTTPException(400, "Некорректное имя")
    if not folder.startswith("train_"):
        raise HTTPException(400, "Некорректный прогон")
    run_dir = os.path.join(RUNS_DIR, folder)
    real = os.path.realpath(run_dir)
    if not real.startswith(os.path.realpath(RUNS_DIR) + os.sep):
        raise HTTPException(400, {"key": "error.invalidPath", "fallback": "Некорректный путь"})
    if not os.path.isdir(real):
        raise HTTPException(404, "Прогон не найден")

    results_csv = os.path.join(run_dir, "output", "train", "results.csv")
    epochs = []
    if os.path.exists(results_csv):
        try:
            with open(results_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                    if not clean.get("epoch"):
                        continue
                    def _f(key):
                        try: return float(clean.get(key, 0) or 0)
                        except Exception: return 0.0
                    epochs.append({
                        "epoch": int(_f("epoch")),
                        "mAP50": _f("metrics/mAP50(B)"),
                        "mAP50_95": _f("metrics/mAP50-95(B)"),
                        "precision": _f("metrics/precision(B)"),
                        "recall": _f("metrics/recall(B)"),
                        "train_box_loss": _f("train/box_loss"),
                        "train_cls_loss": _f("train/cls_loss"),
                        "val_box_loss": _f("val/box_loss"),
                    })
        except Exception:
            log.exception("metrics: parse results.csv failed")

    meta = None
    meta_path = os.path.join(run_dir, "metadata.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = None
    return {"folder": folder, "metadata": meta, "epochs": epochs}

@app.get("/api/train/runs/{folder}/file/{name}")
def train_run_file(folder: str, name: str):
    if not _is_simple_filename(folder) or not folder.startswith("train_"):
        raise HTTPException(400, "Некорректный прогон")
    if not _is_simple_filename(name):
        raise HTTPException(400, "Некорректное имя файла")
    allowed = {
        "confusion_matrix.png", "confusion_matrix_normalized.png",
        "results.png", "val_batch0_pred.jpg", "val_batch1_pred.jpg",
        "val_batch2_pred.jpg", "train_batch0.jpg", "labels.jpg",
        "labels_correlogram.jpg", "F1_curve.png", "P_curve.png",
        "R_curve.png", "PR_curve.png",
    }
    if name not in allowed:
        raise HTTPException(400, "Файл не разрешён")
    path = os.path.join(RUNS_DIR, folder, "output", "train", name)
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(RUNS_DIR) + os.sep):
        raise HTTPException(400, {"key": "error.invalidPath", "fallback": "Некорректный путь"})
    if not os.path.exists(real):
        raise HTTPException(404, "Файл не найден")
    media = "image/png" if name.endswith(".png") else "image/jpeg"
    return FileResponse(real, media_type=media,
                        headers={"Cache-Control": "public, max-age=3600"})

# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
@app.post("/api/train/start")
def train_start(project_id: int = Form(...), base_model: str = Form("yolov8n.pt"),
                pretrain_dataset: str = Form("oiv7"),
                model_name: str = Form(""),
                epochs: int = Form(50), imgsz: int = Form(640),
                freeze: int = Form(8), lr0: float = Form(0.001),
                task: str = Form("detect"),
                family: str = Form("auto"),
                db: Session = Depends(get_db)):
    _rate_limit(_limiter_train, "local", {"key": "error.rateLimitedTrain", "fallback": "Слишком часто запускается обучение"})
    with TRAIN_LOCK:
        if TRAIN_STATE["status"] in ("running", "stopping", "preparing"):
            raise HTTPException(409, {"key": "error.alreadyTraining", "fallback": "Обучение уже идёт"})
        TRAIN_STATE["status"] = "preparing"
    try:
        proj = db.query(Project).filter(Project.id == project_id,
                                         Project.is_deleted.is_(False)).first()
        if not proj:
            raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
        epochs = max(1, min(MAX_EPOCHS, int(epochs)))
        imgsz = max(64, min(2048, int(imgsz)))
        custom_name = ""
        if model_name and model_name.strip():
            custom_name = _sanitize_model_name(model_name)
            if not custom_name:
                raise HTTPException(400, {"key": "error.invalidModelName", "fallback": "Некорректное имя модели"})
        task_clean = task if task in ("detect", "pose") else "detect"
        # V8.7.0: для pose нужны скелеты.
        if task_clean == "pose":
            kp_count = _count_annotations_with_skeleton(db, project_id)
            if kp_count < 30:
                raise HTTPException(400,
                    f"Для обучения pose нужно минимум 30 аннотаций со скелетом "
                    f"(сейчас {kp_count}). Размечай скелеты через Shift+K.")
        if base_model == "__active__" or family == "__active__":
            if task_clean == "pose":
                active = get_active_pose_model_path(db)
            else:
                active = get_active_model_path(db)
            if not active:
                raise HTTPException(400, {"key": "error.noActiveModel", "fallback": "Нет активной модели"})
            model_path = active
        else:
            size_map = {"n": "n", "s": "s", "m": "m", "l": "l", "x": "x"}
            size = size_map.get(base_model, "n")
            _fam = family
            if _fam == "auto":
                _fam = "v11" if task_clean == "pose" else "v8"
            # [STAGE3:YOLO26-APP]
            prefix = ("yolo11" if _fam == "v11"
                      else ("yolo26" if _fam == "v26" else "yolov8"))
            if task_clean == "pose":
                model_path = f"{prefix}{size}-pose.pt"
            elif pretrain_dataset == "oiv7":
                model_path = f"{prefix}{size}-oiv7.pt"
            else:
                model_path = f"{prefix}{size}.pt"
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join(RUNS_DIR, f"train_{run_id}")
        os.makedirs(run_dir, exist_ok=True)
        try:
            if task_clean == "pose":
                yaml_path = prepare_training_dataset_pose(db, project_id, run_dir)
            else:
                yaml_path = prepare_training_dataset(db, project_id, run_dir)
        except Exception as e:
            raise HTTPException(500, f"Не удалось подготовить датасет: {e}")
        with TRAIN_LOCK:
            TRAIN_STATE.update({
                "status": "running", "progress": 0.0,
                "current_epoch": 0, "total_epochs": epochs,
                "message": "Обучение запущено", "log_lines": [],
                "model_name": None, "project_id": project_id,
                "started_at": utcnow().isoformat(), "finished_at": None,
                "run_id": run_id, "task": task_clean,
            })
        TRAIN_EVENT.set()
        log_status("info", "train",
                   f"Обучение запущено: project={project_id}, "
                   f"класс={proj.object_class}, "
                   f"base={os.path.basename(model_path)}, epochs={epochs}, "
                   f"name={custom_name or 'auto'}")
        freeze_layers = max(0, min(MAX_FREEZE_LAYERS, int(freeze)))
        lr0_val = max(1e-5, min(0.1, float(lr0)))
        yolo_cmd = None  # [FIX:always-python-c] Используем python -c для стабильности
        out_dir = os.path.join(run_dir, "output")
        # V8.7.0: pose или detect
        yolo_task = "pose" if task_clean == "pose" else "detect"
        if yolo_cmd:
            args = [yolo_cmd, yolo_task, "train", f"data={yaml_path}", f"model={model_path}",
                    f"epochs={epochs}", f"imgsz={imgsz}", f"project={out_dir}",
                    "name=train", "exist_ok=True", "device=cpu", "verbose=True",
                    f"freeze={freeze_layers}", f"lr0={lr0_val}", "patience=20",
                    "cos_lr=True", "warmup_epochs=3",
                    f"seed={int(getattr(proj, 'random_seed', 42) or 42)}"]  # [STAGE2:yolo-seed]
        else:
            py_code = (
                "import sys, json; "
                "from ultralytics import YOLO; "
                "cfg = json.loads(sys.argv[1]); "
                "YOLO(cfg['model']).train(**cfg['kwargs'])"
            )
            cfg = {
                "model": model_path,
                "task": yolo_task,
                "kwargs": {
                    "data": yaml_path, "epochs": epochs, "imgsz": imgsz,
                    "project": out_dir, "name": "train", "exist_ok": True,
                    "device": "cpu", "verbose": True, "freeze": freeze_layers,
                    "lr0": lr0_val, "patience": 20, "cos_lr": True, "warmup_epochs": 3,
                },
            }
            if getattr(sys, "frozen", False):
                # [FIX:exe-train-worker] В exe запускаем сами себя в режиме воркера
                args = [sys.executable, "--train-worker", json.dumps(cfg)]
            else:
                args = [sys.executable, "-c", py_code, json.dumps(cfg)]
        t = threading.Thread(target=_run_training_thread,
                             args=(args, run_dir, run_id, custom_name), daemon=True)
        t.start()
        return {"status": "started", "run_id": run_id,
                "planned_name": custom_name or f"train_{run_id}.pt"}
    except Exception:
        with TRAIN_LOCK:
            if TRAIN_STATE["status"] == "preparing":
                TRAIN_STATE["status"] = "idle"
        TRAIN_EVENT.set()
        raise

@app.get("/api/train/status")
def train_status(db: Session = Depends(get_db)):
    snap = _train_snapshot()
    return snap

@app.get("/api/projects/{project_id}/skeletons_count")
def skeletons_count(project_id: int, db: Session = Depends(get_db)):
    """V8.7.0: сколько аннотаций проекта имеют скелет."""
    n = _count_annotations_with_skeleton(db, project_id)
    return {"count": n, "min_required": 30}

@app.post("/api/train/stop")
def train_stop():
    global TRAIN_PROCESS
    with TRAIN_LOCK:
        if TRAIN_STATE["status"] != "running":
            return {"status": "not_running"}
        TRAIN_STATE["status"] = "stopping"
        TRAIN_STATE["message"] = "Останавливаю, сохраняю last.pt..."
        proc = TRAIN_PROCESS
    TRAIN_EVENT.set()
    if proc is not None:
        import signal as _signal
        try:
            if os.name == "nt":
                # V7.9.2: на Windows процесс создан с CREATE_NO_WINDOW —
                # у него нет консоли, а CTRL_BREAK_EVENT доставляется только
                # через консоль. Popen.send_signal(SIGINT) на Windows вообще
                # бросает ValueError (поддерживаются только SIGTERM/CTRL_C/CTRL_BREAK).
                # Поэтому переходим сразу к terminate().
                # YOLO сохраняет last.pt после каждой эпохи — чекпоинт не теряется.
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    log.info("stop training (win): hard terminate pid=%s", proc.pid)
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        log.warning("terminate didn't help, killing pid=%s", proc.pid)
                        proc.kill()
                        try:
                            proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            log.error("kill didn't help for pid=%s", proc.pid)
            else:
                # V7.9.3: SIGINT всей process group. torch.multiprocessing
                # спавнит DataLoader-воркеры — они не получают сигнал
                # от родителя, поэтому бьём группу через killpg.
                def _killpg(sig):
                    try:
                        os.killpg(os.getpgid(proc.pid), sig)
                        return True
                    except (ProcessLookupError, PermissionError, OSError):
                        return False

                if not _killpg(_signal.SIGINT):
                    try:
                        proc.send_signal(_signal.SIGINT)
                    except Exception:
                        pass
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    log.warning("training didn't stop on SIGINT, terminating pg")
                    if not _killpg(_signal.SIGTERM):
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        log.warning("training didn't stop on SIGTERM, killing pg")
                        if not _killpg(_signal.SIGKILL):
                            try:
                                proc.kill()
                            except Exception:
                                pass
        except Exception:
            log.exception("stop training failed")
    log_status("warning", "train", "Запрошена остановка обучения (last.pt сохранён)")
    return {"status": "stopping"}

def _live_results_for_run(run_id: str) -> list:
    if not run_id:
        return []
    path = os.path.join(RUNS_DIR, f"train_{run_id}", "output", "train", "results.csv")
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                if not clean.get("epoch"):
                    continue
                def _f(k):
                    try: return float(clean.get(k, 0) or 0)
                    except Exception: return 0.0
                out.append({
                    "epoch": int(_f("epoch")),
                    "mAP50": _f("metrics/mAP50(B)"),
                    "mAP50_95": _f("metrics/mAP50-95(B)"),
                    "precision": _f("metrics/precision(B)"),
                    "recall": _f("metrics/recall(B)"),
                    "train_box_loss": _f("train/box_loss"),
                    "val_box_loss": _f("val/box_loss"),
                })
    except Exception:
        log.exception("live results parse failed")
    return out

@app.get("/api/train/events")
async def train_events():
    async def gen():
        snap = _train_snapshot()
        # V7.9.1: запоминаем последние известные live_epochs между тиками —
        # иначе клиент получает то с ними, то без → мигают графики.
        live_cache = _live_results_for_run(snap.get("run_id"))
        snap["live_epochs"] = live_cache
        yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
        last = json.dumps(snap, ensure_ascii=False)
        tick = 0
        while True:
            await asyncio.get_event_loop().run_in_executor(None, TRAIN_EVENT.wait, 0.6)
            TRAIN_EVENT.clear()
            snap = _train_snapshot()
            tick += 1
            if tick % 5 == 0 or snap["status"] not in ("running", "stopping", "preparing"):
                live_cache = _live_results_for_run(snap.get("run_id"))
            snap["live_epochs"] = live_cache
            payload = json.dumps(snap, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if snap["status"] not in ("running", "stopping", "preparing"):
                break
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/train/reset")
def train_reset():
    with TRAIN_LOCK:
        if TRAIN_STATE["status"] in ("running", "stopping", "preparing"):
            raise HTTPException(409, {"key": "error.trainingRunning", "fallback": "Нельзя сбросить, пока идёт обучение"})
    _train_reset()
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# Batch autolabel
# ---------------------------------------------------------------------------
@app.post("/api/autolabel/batch/start")
def batch_autolabel_start(payload: BatchAutolabelIn, db: Session = Depends(get_db)):
    global BATCH_THREAD
    _rate_limit(_limiter_autolabel, "local", "Слишком много запусков батча")
    with BATCH_LOCK:
        if BATCH_STATE["status"] == "running":
            raise HTTPException(409, {"key": "error.batchRunning", "fallback": "Батч уже идёт"})
        ids = [int(x) for x in (payload.image_ids or [])]
        if not ids:
            raise HTTPException(400, {"key": "error.emptyImageIds", "fallback": "Пустой список image_ids"})
        BATCH_STATE["status"] = "starting"
    model_path = get_active_model_path(db)
    if not model_path:
        with BATCH_LOCK:
            BATCH_STATE["status"] = "idle"
        raise HTTPException(501, {"key": "error.noModel", "fallback": "Активная модель не найдена"})
    if payload.project_id:
        proj = db.query(Project).filter(Project.id == payload.project_id).first()
        if proj:
            try:
                model = _get_yolo_model(model_path)
                if not _resolve_target_class_ids(model, proj.object_class or DEFAULT_OBJECT_CLASS):
                    with BATCH_LOCK:
                        BATCH_STATE["status"] = "idle"
                    raise HTTPException(
                        422,
                        f"Класс «{proj.object_class}» не поддерживается активной моделью. "
                        f"Выбери OIV7 или обучи свою."
                    )
            except HTTPException:
                raise
            except Exception:
                log.exception("batch: cannot verify model classes")
    BATCH_STOP.clear()
    with BATCH_LOCK:
        BATCH_STATE.update({
            "status": "running", "total": len(ids), "done": 0, "failed": 0,
            "current_id": None, "current_filename": "",
            "message": "Запуск...",
            "started_at": utcnow().isoformat(), "finished_at": None,
            "project_id": payload.project_id,
            "added": 0, "skipped": 0,
            "mode": _norm_mode(payload.mode),
        })
    BATCH_EVENT.set()
    t = threading.Thread(target=_batch_worker,
                         args=(ids, model_path, payload.project_id,
                               _norm_mode(payload.mode)), daemon=True)
    BATCH_THREAD = t
    t.start()
    return {"status": "started", "total": len(ids)}

@app.get("/api/autolabel/batch/status")
def batch_autolabel_status():
    return _batch_snapshot()

@app.post("/api/autolabel/batch/stop")
def batch_autolabel_stop():
    with BATCH_LOCK:
        if BATCH_STATE["status"] != "running":
            return {"status": "not_running"}
        BATCH_STATE["message"] = "Останавливаю..."
    BATCH_STOP.set()
    BATCH_EVENT.set()
    return {"status": "stopping"}

@app.get("/api/autolabel/batch/events")
async def batch_autolabel_events():
    async def gen():
        snap = _batch_snapshot()
        yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
        last = json.dumps(snap, ensure_ascii=False)
        while True:
            await asyncio.get_event_loop().run_in_executor(None, BATCH_EVENT.wait, 1.0)
            BATCH_EVENT.clear()
            snap = _batch_snapshot()
            payload = json.dumps(snap, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if snap["status"] != "running":
                break
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ============================================================================
# V8.8.0: трекинг кадров через ByteTrack.
# ============================================================================

TRACK_STATE = {
    "status": "idle", "video_id": None,
    "total": 0, "done": 0, "failed": 0,
    "tracks": 0, "assignments": 0,
    "message": "", "started_at": None, "finished_at": None,
}
TRACK_LOCK = threading.Lock()
TRACK_STOP = threading.Event()
TRACK_THREAD = None
TRACK_EVENT = threading.Event()

def _track_snapshot():
    with TRACK_LOCK:
        return dict(TRACK_STATE)

def _track_set(**kw):
    with TRACK_LOCK:
        TRACK_STATE.update(kw)
    TRACK_EVENT.set()

def _track_worker(video_id, project_id, model_path):
    global TRACK_THREAD
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            _track_set(status="error", message="Video not found",
                       finished_at=utcnow().isoformat())
            return

        frames = (db.query(ImageModel)
                    .filter(ImageModel.video_id == video_id,
                            ImageModel.is_deleted.is_(False))
                    .order_by(ImageModel.frame_index).all())
        if not frames:
            _track_set(status="error", message="No frames for this video",
                       finished_at=utcnow().isoformat())
            return

        # V8.8.0-fix: animal_id — поле Annotation, не ImageModel.
        max_aid = (db.query(func.max(Annotation.animal_id))
                     .join(ImageModel, Annotation.image_id == ImageModel.id)
                     .filter(ImageModel.project_id == project_id,
                             Annotation.animal_id.isnot(None))
                     .scalar() or 0)
        next_aid = int(max_aid) + 1

        anns_by_image = defaultdict(list)
        all_anns = (db.query(Annotation)
                      .filter(Annotation.image_id.in_([f.id for f in frames]))
                      .order_by(Annotation.id).all())
        for a in all_anns:
            anns_by_image[a.image_id].append(a)

        try:
            model = _get_yolo_model(model_path)
            model.predictor = None
        except Exception as e:
            _track_set(status="error",
                       message="Model load failed: %s" % _safe_error_message(e),
                       finished_at=utcnow().isoformat())
            return

        # V8.8.0-fix: ultralytics не принимает генератор — нужен список путей.
        # Отсеиваем несуществующие файлы, сохраняем порядок по frame_index.
        frame_paths = []
        for im in frames:
            if im.path and os.path.exists(im.path):
                frame_paths.append(im.path)
        if not frame_paths:
            _track_set(status="error", message="No files on disk for this video",
                       finished_at=utcnow().isoformat())
            return

        _track_set(status="running", video_id=video_id, total=len(frame_paths),
                   done=0, failed=0, tracks=0, assignments=0,
                   started_at=utcnow().isoformat(), finished_at=None,
                   message="Tracking...")

        assignments = 0
        pending_commit = 0

        from services.tracker_service import TrackerState, process_frame_detections
        tracker_state = TrackerState()

        try:
            results_iter = model.track(
                source=frame_paths,
                stream=True,
                persist=True,
                tracker="bytetrack.yaml",
                conf=0.25,
                verbose=False,
            )
        except Exception as e:
            _track_set(status="error",
                       message="Track init failed: %s" % _safe_error_message(e),
                       finished_at=utcnow().isoformat())
            return

        idx = -1
        try:
            for idx, r in enumerate(results_iter):
                if TRACK_STOP.is_set():
                    db.commit()
                    _track_set(status="stopped", message="Stopped by user",
                               finished_at=utcnow().isoformat())
                    return
                if idx >= len(frames):
                    break
                im = frames[idx]
                anns = anns_by_image.get(im.id, [])
                if not anns:
                    with TRACK_LOCK:
                        TRACK_STATE["done"] = idx + 1
                    TRACK_EVENT.set()
                    continue

                xyxy = None
                tids = None
                try:
                    if r.boxes is not None and r.boxes.id is not None:
                        xyxy = r.boxes.xyxy.cpu().numpy()
                        tids = r.boxes.id.cpu().numpy()
                except Exception:
                    xyxy = None
                    tids = None

                if xyxy is not None and tids is not None and len(xyxy) == len(tids):
                    W = im.width or 640
                    H = im.height or 640
                    frame_dets = []
                    for k in range(len(xyxy)):
                        try:
                            x1, y1, x2, y2 = xyxy[k].tolist()
                            track_id = int(tids[k])
                        except (TypeError, ValueError):
                            continue
                        if track_id <= 0:
                            continue
                        frame_dets.append({
                            "track_id": track_id,
                            "x": max(0.0, x1 / W),
                            "y": max(0.0, y1 / H),
                            "w": max(0.0, min(1.0, (x2 - x1) / W)),
                            "h": max(0.0, min(1.0, (y2 - y1) / H)),
                        })

                    updates, next_aid, assigned = process_frame_detections(
                        frame_dets, anns, tracker_state, next_aid, im.path, idx
                    )
                    assignments += assigned
                    pending_commit += len(updates)

                    if pending_commit >= 20:
                        _db_commit_safe(db)
                        pending_commit = 0

                with TRACK_LOCK:
                    TRACK_STATE["done"] = idx + 1
                    TRACK_STATE["tracks"] = len(tracker_state.track_to_aid)
                    TRACK_STATE["assignments"] = assignments
                TRACK_EVENT.set()
        finally:
            try:
                results_iter.close()
            except Exception:
                pass

        _db_commit_safe(db)
        _track_set(status="done", message="Tracking complete",
                   tracks=len(tracker_state.track_to_aid), assignments=assignments,
                   done=len(frame_paths), finished_at=utcnow().isoformat())
        log_status("info", "video",
                   "Трекинг видео #%d: кадров %d, треков %d, назначено %d"
                   % (video_id, len(frames), len(track_to_aid), assignments))
    except Exception as e:
        log.exception("track worker failed")
        try:
            db.rollback()
        except Exception:
            pass
        _track_set(status="error",
                   message=_safe_error_message(e),
                   finished_at=utcnow().isoformat())
    finally:
        try:
            db.close()
        except Exception:
            pass
        with TRACK_LOCK:
            TRACK_THREAD = None
        TRACK_EVENT.set()
        gc.collect()

# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------
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
        try:
            pil = Image.open(fp).convert("RGB")
            _orig_w, _orig_h = pil.size  # [PATCH:STAGE1_VIDEO_ORIG_DIMS]
            pil = letterbox(pil, FIXED_SIZE, LETTERBOX_FILL)
            new_fname = f"{uuid.uuid4().hex}.jpg"
            new_path = os.path.join(UPLOAD_DIR, new_fname)
            pil.save(new_path, "JPEG", quality=85) # [PERF:jpg-85]
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
        except Exception as e:
            log.error('DB insert error during video upload: %s', e)
            db.rollback()
            raise HTTPException(500, f'Ошибка сохранения кадра в БД: {e}')
        _queue_thumb(im.id, im.path)
        try:
            from services.auto_blur_service import schedule_auto_blur
            schedule_auto_blur(im.id, project_id)
        except Exception:
            pass
        if first_image_id is None:
            first_image_id = im.id
        inserted += 1
        _remove_file_safe(fp)
        if inserted % 50 == 0:
            db.commit()
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
        rest = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
                  .filter(ImageModel.project_id == project_id,
                          ImageModel.is_deleted.is_(False),
                          ImageModel.id != image_id,
                          ImageModel.phash.isnot(None),
                          ~ImageModel.phash.like(f"{prefix}%"))
                  .limit(5000).all())  # V7.9.3: было 2000
        for r in rest:
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

def list_tags(project_id: int, db: Session = Depends(get_db)):
    tags = db.query(Tag).filter(Tag.project_id == project_id).order_by(Tag.name).all()
    tag_ids = [t.id for t in tags] or [0]
    counts = dict(
        db.query(ImageTag.tag_id, func.count(ImageTag.image_id))
          .join(ImageModel, ImageModel.id == ImageTag.image_id)
          .filter(ImageTag.tag_id.in_(tag_ids),
                  ImageModel.is_deleted.is_(False))
          .group_by(ImageTag.tag_id).all()
    )
    return [{"id": t.id, "name": t.name, "color": t.color or "#0071e3",
             "count": int(counts.get(t.id, 0))} for t in tags]

def create_tag(project_id: int, name: str = Form(...), color: str = Form("#0071e3"),
               db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    name = name.strip()
    if not name:
        raise HTTPException(400, {"key": "error.emptyTagName", "fallback": "Пустое имя тега"})
    if len(name) > 64:
        raise HTTPException(400, "Слишком длинное имя")
    color_clean = (color or "").strip()
    if not _HEX_COLOR_RE.match(color_clean):
        raise HTTPException(400, {"key": "error.invalidColor", "params": {"c": color}, "fallback": f"Некорректный цвет: {color!r}"})
    existing = db.query(Tag).filter(Tag.project_id == project_id, Tag.name == name).first()
    if existing:
        raise HTTPException(409, {"key": "error.tagExists", "fallback": "Такой тег уже существует"})
    t = Tag(project_id=project_id, name=name, color=color_clean.lower())
    db.add(t)
    db.commit()
    db.refresh(t)
    log_status("success", "tag", f"Создан тег «{name}»")
    return {"id": t.id, "name": t.name, "color": t.color, "count": 0}

def update_tag(tag_id: int,
               name: Optional[str] = Form(None),
               color: Optional[str] = Form(None),
               db: Session = Depends(get_db)):
    t = db.query(Tag).filter(Tag.id == tag_id).first()
    if not t:
        raise HTTPException(404, {"key": "error.tagNotFound", "fallback": "Tag not found"})
    if name is not None:
        nm = name.strip()
        if not nm:
            raise HTTPException(400, {"key": "error.emptyName", "fallback": "Пустое имя"})
        dup = db.query(Tag).filter(Tag.project_id == t.project_id,
                                     Tag.name == nm, Tag.id != t.id).first()
        if dup:
            raise HTTPException(409, {"key": "error.tagExists", "fallback": "Такой тег уже существует"})
        t.name = nm
    if color is not None:
        c = color.strip()
        if not _HEX_COLOR_RE.match(c):
            raise HTTPException(400, f"Некорректный цвет: {color!r}")
        t.color = c.lower()
    db.commit()
    return {"id": t.id, "name": t.name, "color": t.color}

def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    t = db.query(Tag).filter(Tag.id == tag_id).first()
    if not t:
        raise HTTPException(404, {"key": "error.tagNotFound", "fallback": "Tag not found"})
    db.query(ImageTag).filter(ImageTag.tag_id == tag_id).delete()
    db.delete(t)
    db.commit()
    log_status("warning", "tag", f"Удалён тег «{t.name}»")
    return {"status": "ok"}

def get_image_tags(image_id: int, db: Session = Depends(get_db)):
    rows = (db.query(Tag).join(ImageTag, ImageTag.tag_id == Tag.id)
              .filter(ImageTag.image_id == image_id).all())
    return [{"id": t.id, "name": t.name, "color": t.color or "#0071e3"} for t in rows]

def set_image_tags(image_id: int, tag_ids: list = Body(...),
                   db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    db.query(ImageTag).filter(ImageTag.image_id == image_id).delete()
    for tid in tag_ids:
        t = db.query(Tag).filter(Tag.id == tid, Tag.project_id == img.project_id).first()
        if t:
            db.add(ImageTag(image_id=image_id, tag_id=tid))
    db.commit()
    return {"status": "ok", "count": len(tag_ids)}

def batch_set_tags(payload: BatchTagsIn, db: Session = Depends(get_db)):
    if not payload.image_ids:
        return {"status": "ok", "updated": 0, "added": 0, "removed": 0}
    imgs = (db.query(ImageModel)
              .filter(ImageModel.id.in_(payload.image_ids)).all())
    if not imgs:
        raise HTTPException(404, "Изображения не найдены")
    project_ids = {im.project_id for im in imgs}
    if len(project_ids) > 1:
        raise HTTPException(400, "Изображения из разных проектов")
    pid = project_ids.pop()
    valid_add = []
    if payload.add:
        valid_add = [t.id for t in db.query(Tag).filter(
            Tag.id.in_(payload.add), Tag.project_id == pid).all()]
    valid_remove = []
    if payload.remove:
        valid_remove = [t.id for t in db.query(Tag).filter(
            Tag.id.in_(payload.remove), Tag.project_id == pid).all()]
    if valid_remove:
        db.query(ImageTag).filter(
            ImageTag.image_id.in_(payload.image_ids),
            ImageTag.tag_id.in_(valid_remove)
        ).delete(synchronize_session=False)
    if valid_add:
        existing_links = set()
        rows = (db.query(ImageTag.image_id, ImageTag.tag_id)
                  .filter(ImageTag.image_id.in_(payload.image_ids),
                          ImageTag.tag_id.in_(valid_add)).all())
        for iid, tid in rows:
            existing_links.add((iid, tid))
        for im in imgs:
            for tid in valid_add:
                if (im.id, tid) not in existing_links:
                    db.add(ImageTag(image_id=im.id, tag_id=tid))
    db.commit()
    return {"status": "ok", "updated": len(imgs),
            "added": len(valid_add), "removed": len(valid_remove)}

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

def _bulk_transfer(db, payload: BulkMoveCopyIn, copy: bool):
    ids = payload.image_ids or []
    if not ids:
        raise HTTPException(400, "Пустой список")
    if len(ids) > 2000:
        raise HTTPException(400, "Максимум 2000 за раз")
    dst_proj = db.query(Project).filter(Project.id == payload.target_project_id,
                                         Project.is_deleted.is_(False)).first()
    if not dst_proj:
        raise HTTPException(404, "Целевой проект не найден")
    imgs = db.query(ImageModel).filter(ImageModel.id.in_(ids),
                                        ImageModel.is_deleted.is_(False)).all()
    if not imgs:
        raise HTTPException(404, "Изображения не найдены")
    if any(im.project_id == dst_proj.id for im in imgs):
        raise HTTPException(400, "Некоторые изображения уже в этом проекте")
    dst_class = dst_proj.object_class or DEFAULT_OBJECT_CLASS
    used_names = {fn for (fn,) in db.query(ImageModel.filename)
                    .filter(ImageModel.project_id == dst_proj.id,
                            ImageModel.is_deleted.is_(False)).all()}
    moved = 0
    for im in imgs:
        src_path = im.path
        new_path = src_path
        if copy:
            new_fname = f"{uuid.uuid4().hex}.jpg"
            new_path = os.path.join(UPLOAD_DIR, new_fname)
            try:
                shutil.copyfile(src_path, new_path)
            except OSError:
                continue
        final_name = _unique_name_mem(im.filename, used_names)
        if copy:
            try:
                new_im = ImageModel(
                    project_id=dst_proj.id, filename=final_name, path=new_path,
                    width=im.width, height=im.height,
                    is_deleted=False, phash=im.phash, is_hard=im.is_hard,
                    video_id=None, frame_index=None,
                    created_at=im.created_at or utcnow(), file_size=im.file_size,
                )
                db.add(new_im)
                db.flush()
                anns = db.query(Annotation).filter(Annotation.image_id == im.id).all()

                # V10.4.1: копирование проекта → проекта не должно терять скелеты
                # и атрибуты рамок (behavior/animal_id).
                _src_ann_ids = [a.id for a in anns]
                _kp_map = defaultdict(list)
                if _src_ann_ids:
                    for _kp in (db.query(Keypoint)
                                  .filter(Keypoint.annotation_id.in_(_src_ann_ids))
                                  .all()):
                        _kp_map[_kp.annotation_id].append(_kp)
                for a in anns:
                    _new_ann = Annotation(image_id=new_im.id,
                                          x=a.x, y=a.y, w=a.w, h=a.h,
                                          label=dst_class, confidence=a.confidence,
                                          is_frozen=a.is_frozen,
                                          behavior=a.behavior,
                                          animal_id=a.animal_id)
                    db.add(_new_ann)
                    db.flush()
                    for _kp in _kp_map.get(a.id, []):
                        db.add(Keypoint(annotation_id=_new_ann.id,
                                        name=_kp.name, x=_kp.x, y=_kp.y,
                                        visibility=_kp.visibility))
                src_tag_ids = [it.tag_id for it in db.query(ImageTag).filter(ImageTag.image_id == im.id).all()]
                if src_tag_ids:
                    src_tags = {t.id: t.name for t in db.query(Tag).filter(Tag.id.in_(src_tag_ids)).all()}
                    dst_tags = {t.name: t.id for t in db.query(Tag).filter(Tag.project_id == dst_proj.id).all()}
                    for tid in src_tag_ids:
                        tname = src_tags.get(tid)
                        dst_tid = dst_tags.get(tname) if tname else None
                        if dst_tid:
                            db.add(ImageTag(image_id=new_im.id, tag_id=dst_tid))
                _queue_thumb(new_im.id, new_im.path)
            except Exception as e:
                db.rollback()
                if os.path.exists(new_path):
                    _remove_file_safe(new_path)
                log.error("Ошибка при копировании БД для %s: %s", im.filename, e)
                continue
        else:
            im.project_id = dst_proj.id
            im.filename = final_name
            im.video_id = None
            im.frame_index = None
            db.query(Annotation).filter(Annotation.image_id == im.id).update(
                {"label": dst_class}, synchronize_session=False
            )
        moved += 1
    db.commit()
    action = "Скопировано" if copy else "Перемещено"
    log_status("info", "project",
               f"{action}: {moved} изображений → проект «{dst_proj.name}»")
    return {"status": "ok", "moved": moved, "action": "copy" if copy else "move"}

@app.post("/api/images/bulk_move_to_project")
def bulk_move(payload: BulkMoveCopyIn, db: Session = Depends(get_db)):
    return _bulk_transfer(db, payload, copy=False)

@app.post("/api/images/bulk_copy_to_project")
def bulk_copy(payload: BulkMoveCopyIn, db: Session = Depends(get_db)):
    return _bulk_transfer(db, payload, copy=True)

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

def _process_dataset_zip(zip_path: str, project_id: int, db, cancel_event=None) -> dict:
    proj = db.query(Project).filter(Project.id == project_id,
                                     Project.is_deleted.is_(False)).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    project_class = proj.object_class or DEFAULT_OBJECT_CLASS

    tmp_dir = tempfile.mkdtemp(prefix="pdb_import_", dir=IMPORT_DIR)
    try:
        try:
            with zipfile.ZipFile(zip_path) as z:
                _safe_extract_zip(z, tmp_dir)
        except zipfile.BadZipFile:
            raise HTTPException(400, {"key": "error.invalidZip", "fallback": "Файл не является zip-архивом"})

        fmt, src = detect_format(tmp_dir)
        image_files_peek = _collect_image_files(tmp_dir)
        if not fmt and not image_files_peek:
            raise HTTPException(400, "Архив пуст или не содержит данных")
        if not fmt:
            fmt = "images_only"

        existing = (db.query(ImageModel)
                      .filter(ImageModel.project_id == project_id,
                              ImageModel.is_deleted.is_(False)).all())
        by_stem = {}
        for im in existing:
            stem, _ = _split_name_ext(im.filename)
            by_stem[stem.lower()] = im
        used_names = {fn for (fn,) in db.query(ImageModel.filename)
                                        .filter(ImageModel.project_id == project_id,
                                                ImageModel.is_deleted.is_(False))
                                        .all()}
        phash_buckets = defaultdict(list)
        for r in db.query(ImageModel.id, ImageModel.filename, ImageModel.phash).filter(
                ImageModel.project_id == project_id,
                ImageModel.is_deleted.is_(False),
                ImageModel.phash.isnot(None)).all():
            if r.phash and len(r.phash) >= 4:
                phash_buckets[r.phash[:4]].append(
                    (r.id, r.filename, r.phash, _hex_to_int(r.phash))
                )

        def _find_dup_mem(ph):
            if not ph or len(ph) < 4:
                return None
            target_b = ph[:4]
            target_int = _hex_to_int(ph)
            for (_rid, _fn, p, p_int) in phash_buckets.get(target_b, []):
                if _hamming_int(target_int, p_int) <= PHASH_DUPLICATE_THRESHOLD:
                    return (_rid, _fn, p)
            for b in list(phash_buckets.keys()):
                if b == target_b:
                    continue
                for (_rid, _fn, p, p_int) in phash_buckets[b]:
                    if _hamming_int(target_int, p_int) <= PHASH_DUPLICATE_THRESHOLD:
                        return (_rid, _fn, p)
            return None

        imported_images = 0
        skipped_duplicates = 0
        failed_images = 0
        pending = []

        def _flush_pending():
            nonlocal pending
            if not pending:
                return
            db.flush()
            for (im_x, path_x, stem_x) in pending:
                _queue_thumb(im_x.id, path_x)
                try:
                    from services.auto_blur_service import schedule_auto_blur
                    schedule_auto_blur(im_x.id, project_id)
                except Exception:
                    pass
                by_stem[stem_x] = im_x
            pending = []

        total_files = len(image_files_peek)
        for img_idx, img_path in enumerate(image_files_peek):
            if img_idx % 10 == 0:
                _update_import_progress(project_id, "process", img_idx, total_files, "Обработка изображений")

            # V10.4.1: проверка отмены до обработки каждого файла.
            if cancel_event and cancel_event.is_set():
                db.rollback()
                raise HTTPException(499, "Импорт отменён пользователем")
            original_name = os.path.basename(img_path)
            stem_l = _basename_no_ext(original_name)
            if stem_l in by_stem:
                continue
            try:
                with open(img_path, "rb") as f:
                    head = f.read(16)
                if not _detect_image_format(head):
                    failed_images += 1
                    continue
            except OSError:
                failed_images += 1
                continue
            try:
                pil = Image.open(img_path).convert("RGB")
            except Exception:
                failed_images += 1
                continue
            _orig_w, _orig_h = pil.size  # [PATCH:STAGE1_IMPORT_ORIG_DIMS]
            pil = letterbox(pil, FIXED_SIZE, LETTERBOX_FILL)
            new_fname = f"{uuid.uuid4().hex}.jpg"
            new_path = os.path.join(UPLOAD_DIR, new_fname)
            try:
                pil.save(new_path, "JPEG", quality=95)
            except Exception:
                failed_images += 1
                continue
            try:
                ph = phash_hex(new_path)
            except Exception:
                ph = ""
            if ph:
                dup = _find_dup_mem(ph)
                if dup:
                    _remove_file_safe(new_path)
                    skipped_duplicates += 1
                    continue
            display_name = sanitize_display_name(original_name, fallback=new_fname)
            unique_name = _unique_name_mem(display_name, used_names)
            try:
                fsize = os.path.getsize(new_path)
            except OSError:
                fsize = 0
            im = ImageModel(
                project_id=project_id, filename=unique_name, path=new_path,
                width=FIXED_SIZE[0], height=FIXED_SIZE[1],
                original_width=_orig_w, original_height=_orig_h,  # [PATCH:STAGE1_IMPORT_ORIG_DIMS]
                is_deleted=False, phash=ph or None, is_hard=False,
                created_at=utcnow(), file_size=fsize,
            )
            db.add(im)
            if ph and len(ph) >= 4:
                phash_buckets[ph[:4]].append(
                    (None, unique_name, ph, _hex_to_int(ph))
                )
            pending.append((im, new_path, stem_l))
            imported_images += 1
            if len(pending) >= BATCH_IMPORT_CHUNK:
                _flush_pending()
        _flush_pending()
        db.commit()
        _invalidate_phash_index(project_id)

        parsed = {}
        if fmt == "coco":
            parsed = parse_coco(src, default_label=project_class)
        elif fmt == "yolo":
            parsed = parse_yolo(tmp_dir, default_label=project_class)
        elif fmt == "cvat":
            from services.cvat_service import parse_cvat_xml
            parsed = parse_cvat_xml(src)
        elif fmt == "ls":
            parsed = parse_label_studio(src, default_label=project_class)

        matched = 0
        added_anns = 0
        unmatched = []
        image_ids_to_clear = []
        anns_to_add = []
        for stem, boxes in parsed.items():
            im = by_stem.get(stem)
            if not im:
                unmatched.append(stem)
                continue
            image_ids_to_clear.append(im.id)
            for b in boxes:
                new_ann = Annotation(
                    image_id=im.id,
                    x=max(0.0, min(1.0, b["x"])),
                    y=max(0.0, min(1.0, b["y"])),
                    w=max(0.0, min(1.0, b["w"])),
                    h=max(0.0, min(1.0, b["h"])),
                    label=b.get("label", project_class),
                    confidence=b.get("confidence"),
                    is_frozen=False,
                    animal_id=b.get("animal_id"),
                    behavior=b.get("behavior"),
                )
                db.add(new_ann)
                anns_to_add.append((new_ann, b.get("keypoints", [])))
                added_anns += 1
            matched += 1

        if image_ids_to_clear:
            db.query(Annotation).filter(
                Annotation.image_id.in_(image_ids_to_clear)
            ).delete(synchronize_session=False)

        if anns_to_add:
            db.flush()
            for new_ann, kps in anns_to_add:
                for kp in kps:
                    nm = str(kp.get("name", "")).strip()
                    if nm in KEYPOINT_VALID:
                        db.add(Keypoint(
                            annotation_id=new_ann.id,
                            name=nm,
                            x=max(0.0, min(1.0, float(kp.get("x", 0)))),
                            y=max(0.0, min(1.0, float(kp.get("y", 0)))),
                            visibility=max(0.0, min(1.0, float(kp.get("visibility", 1.0))))
                        ))
        db.commit()

        log_status("success", "import",
                   f"Импорт проекта #{project_id}: формат {fmt}, класс «{project_class}», "
                   f"+{imported_images} фото, дубл. {skipped_duplicates}, "
                   f"рамок {added_anns}, не найдено {len(unmatched)}")
        return {"status": "ok", "format": fmt,
                "imported_images": imported_images,
                "skipped_duplicates": skipped_duplicates,
                "failed_images": failed_images,
                "matched_images": matched,
                "added_annotations": added_anns,
                "unmatched": unmatched[:50],
                "unmatched_count": len(unmatched)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# [V13.1.0:import-progress]
IMPORT_PROGRESS = {}
import threading

def _update_import_progress(pid, stage, done=0, total=0, msg="", error=None):
    IMPORT_PROGRESS[pid] = {
        "stage": stage, "done": done, "total": total, "msg": msg,
        "error": error, "updated_at": time.time()
    }

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
                       db: Session = Depends(get_db)):
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
        return _process_dataset_zip(tmp_zip, project_id, db, cancel_event)
    finally:
        _remove_file_safe(tmp_zip)

# ---------------------------------------------------------------------------
# External importers
# ---------------------------------------------------------------------------
def _download_to_file(url: str, dest: str, timeout: int = 900,
                       extra_headers: Optional[dict] = None,
                       retries: int = 2) -> None:
    """V7.9.3: 3 попытки + exponential backoff (1.5s, 3s).

    4xx (кроме 429) не retry-им — это не сетевой сбой, а наша ошибка.
    """
    headers = {"User-Agent": "DatasetBuilder/7.9.3"}
    if extra_headers:
        headers.update(extra_headers)
    last_exc = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                with open(dest, "wb") as f:
                    shutil.copyfileobj(r, f, length=1024 * 1024)
            return
        except urllib.error.HTTPError as e:
            last_exc = e
            if 400 <= e.code < 500 and e.code != 429:
                raise
        except Exception as e:
            last_exc = e
        if attempt < retries:
            delay = 1.5 * (2 ** attempt)
            log.warning("_download_to_file attempt %d failed: %s; retry in %.1fs",
                        attempt + 1, last_exc, delay)
            time.sleep(delay)
    raise last_exc

# V7.8.4: общий скелет для внешних импортёров — временный zip + проверка
@contextmanager
def _external_import_tmp(prefix: str):
    """Временный zip для внешнего импорта. Убирается автоматически."""
    tmp = os.path.join(IMPORT_DIR, f"_{prefix}_{uuid.uuid4().hex}.zip")
    try:
        yield tmp
    finally:
        _remove_file_safe(tmp)

def _finalize_external_import(tmp_zip: str, project_id: int, db,
                              source_name: str = "источник"):
    """Проверяет, что скачался валидный zip, и передаёт его в _process_dataset_zip."""
    if not os.path.exists(tmp_zip) or os.path.getsize(tmp_zip) < 100:
        raise HTTPException(400, f"Пустой ответ от {source_name}")
    with open(tmp_zip, "rb") as f:
        if f.read(2) != b"PK":
            raise HTTPException(400, f"{source_name} вернул не zip")
    return _process_dataset_zip(tmp_zip, project_id, db)

@app.post("/api/projects/{project_id}/import/roboflow")
def import_roboflow(project_id: int, payload: ImportRoboflowIn,
                     db: Session = Depends(get_db)):
    _rate_limit(_limiter_import, "roboflow", "Слишком много импортов. Подожди.")
    if not payload.api_key or not payload.workspace or not payload.project:
        raise HTTPException(400, "api_key, workspace, project обязательны")
    url = (f"https://api.roboflow.com/{payload.workspace}/{payload.project}/"
           f"{payload.version}/coco?api_key={payload.api_key}")
    with _external_import_tmp("roboflow") as tmp_zip:
        try:
            _download_to_file(url, tmp_zip)
            return _finalize_external_import(tmp_zip, project_id, db, "Roboflow")
        except HTTPException:
            raise
        except Exception as e:
            log.exception("roboflow import failed")
            raise HTTPException(500, f"Roboflow: {_safe_error_message(e)}")

@app.post("/api/projects/{project_id}/import/supervisely")
def import_supervisely(project_id: int, payload: ImportSuperviselyIn,
                        db: Session = Depends(get_db)):
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
            return _finalize_external_import(tmp_zip, project_id, db, "Supervisely")
        except HTTPException:
            raise
        except Exception as e:
            log.exception("supervisely import failed")
            raise HTTPException(500, f"Supervisely: {_safe_error_message(e)}")

@app.post("/api/projects/{project_id}/import/url")
def import_url(project_id: int, payload: ImportUrlIn,
                db: Session = Depends(get_db)):
    _rate_limit(_limiter_import, "url", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(400, "URL обязателен")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(400, "URL должен начинаться с http(s)://")
    # V7.9.3: единый context manager, включая single-image fallback.
    with _external_import_tmp("url") as tmp_file:
        try:
            _download_to_file(url, tmp_file)
            if not os.path.exists(tmp_file) or os.path.getsize(tmp_file) < 100:
                raise HTTPException(400, "Пустой ответ")
            with open(tmp_file, "rb") as f:
                head = f.read(4)
            if head[:2] == b"PK":
                return _process_dataset_zip(tmp_file, project_id, db)
            with open(tmp_file, "rb") as f:
                h64 = f.read(64)
            fmt = _detect_image_format(h64)
            if fmt:
                with _external_import_tmp("url_single") as single_zip:
                    with zipfile.ZipFile(single_zip, "w") as z:
                        fname = payload.filename or os.path.basename(url.split("?", 1)[0]) or "image"
                        z.write(tmp_file, fname)
                    return _process_dataset_zip(single_zip, project_id, db)
            raise HTTPException(400, "Ссылка не ведёт на zip или картинку")
        except HTTPException:
            raise
        except Exception as e:
            log.exception("url import failed")
            raise HTTPException(500, f"URL: {_safe_error_message(e)}")

@app.post("/api/projects/{project_id}/import/local_folder")
def import_local_folder(project_id: int, payload: ImportLocalFolderIn,
                         db: Session = Depends(get_db)):
    _rate_limit(_limiter_import, "local_folder", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
    src = (payload.path or "").strip()
    if not src:
        raise HTTPException(400, "Путь обязателен")
    if not os.path.isabs(src):
        raise HTTPException(400, "Путь должен быть абсолютным")
    if not os.path.isdir(src):
        raise HTTPException(404, f"Папка не найдена: {src}")
    imgs = []
    if payload.recursive:
        for root, _dirs, files in os.walk(src):
            for f in files:
                if _is_image_ext(f):
                    imgs.append(os.path.join(root, f))
    else:
        for f in os.listdir(src):
            if _is_image_ext(f):
                imgs.append(os.path.join(src, f))
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
            return _process_dataset_zip(tmp_zip, project_id, db, cancel_event)
        except HTTPException:
            raise
        except Exception as e:
            log.exception("local folder import failed")
            raise HTTPException(500, f"Папка: {_safe_error_message(e)}")

def _http_get_json(url: str, headers: dict, timeout: int = 120,
                    retries: int = 2) -> dict:
    """V7.9.3: retries + backoff. 4xx не retry-им."""
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
                        attempt + 1, last_exc, delay)
            time.sleep(delay)
    raise last_exc

def _http_post_json(url: str, headers: dict, body: dict, timeout: int = 120,
                     retries: int = 2) -> dict:
    """V7.9.3: retries + backoff. 4xx не retry-им — payload/ключа не поправим."""
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
                        attempt + 1, last_exc, delay)
            time.sleep(delay)
    raise last_exc

@app.post("/api/projects/{project_id}/import/labelbox")
def import_labelbox(project_id: int, payload: ImportLabelboxIn,
                     db: Session = Depends(get_db)):
    _rate_limit(_limiter_import, "labelbox", {"key": "error.rateLimitedImport", "fallback": "Слишком много импортов."})
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
            return _process_dataset_zip(tmp_zip, project_id, db, cancel_event)
        finally:
            _remove_file_safe(tmp_zip)
    finally:
        _remove_file_safe(tmp_json)

@app.post("/api/projects/{project_id}/import/scale")
def import_scale(project_id: int, payload: ImportScaleIn,
                  db: Session = Depends(get_db)):
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
        return _finalize_external_import(tmp_zip, project_id, db, "Scale AI")

@app.post("/api/projects/{project_id}/import/darwin")
def import_darwin(project_id: int, payload: ImportDarwinIn,
                   db: Session = Depends(get_db)):
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
        return _finalize_external_import(tmp_zip, project_id, db, "Darwin")

# ---------------------------------------------------------------------------
# Бэкап проекта
# ---------------------------------------------------------------------------
@app.post("/api/projects/{project_id}/backup")
def backup_project(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    safe_name = re.sub(r'[^A-Za-z0-9_\-]+', '_', proj.name).strip('_')[:60] or f"project_{project_id}"
    zip_name = f"backup_project_{project_id}_{safe_name}.zip"
    zip_path = os.path.join(BACKUP_DIR, zip_name)
    tmp_path = zip_path + ".part"
    images = (db.query(ImageModel)
                .filter(ImageModel.project_id == project_id,
                        ImageModel.is_deleted.is_(False)).all())
    ids = [im.id for im in images]
    annotations = defaultdict(list)
    # V10.4.1: бэкап должен сохранять весь набор полей (V8.3+ behavior/animal_id,
    # V8.5+ keypoints). Раньше восстанавливался только bbox — данные терялись.
    _kp_by_ann = defaultdict(list)
    if ids:
        rows = db.query(Annotation).filter(Annotation.image_id.in_(ids)).all()
        _ann_ids_bp = [a.id for a in rows]
        if _ann_ids_bp:
            for _kp in (db.query(Keypoint)
                          .filter(Keypoint.annotation_id.in_(_ann_ids_bp))
                          .all()):
                _kp_by_ann[_kp.annotation_id].append({
                    "name": _kp.name, "x": _kp.x, "y": _kp.y,
                    "visibility": _kp.visibility,
                })
        for a in rows:
            annotations[str(a.image_id)].append({
                "x": a.x, "y": a.y, "w": a.w, "h": a.h,
                "label": a.label, "confidence": a.confidence,
                "frozen": bool(a.is_frozen),
                "behavior": a.behavior,
                "animal_id": a.animal_id,
                "keypoints": _kp_by_ann.get(a.id, []),
            })
    tags = db.query(Tag).filter(Tag.project_id == project_id).all()
    tags_out = []
    for t in tags:
        img_ids = [it.image_id for it in db.query(ImageTag).filter(ImageTag.tag_id == t.id).all()]
        tags_out.append({"id": t.id, "name": t.name, "color": t.color, "image_ids": img_ids})
    meta = {
        "app_version": APP_VERSION, "backup_version": 1, "is_backup": True,
        "created_at": utcnow().isoformat(),
        "project_id": proj.id, "project_name": proj.name,
        "project_created_at": proj.created_at.isoformat() if proj.created_at else None,
        "object_class": proj.object_class or DEFAULT_OBJECT_CLASS,
        "object_class_source": proj.object_class_source or "list",
        "images_count": len(images),
        "tags_count": len(tags_out),
        "annotations_count": sum(len(v) for v in annotations.values()),
    }
    images_index = [{
        "id": im.id, "filename": im.filename, "width": im.width,
        "height": im.height, "is_hard": bool(im.is_hard), "phash": im.phash,
    } for im in images]
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
            z.writestr("images_index.json", json.dumps(images_index, ensure_ascii=False, indent=2))
            z.writestr("annotations.json", json.dumps(dict(annotations), ensure_ascii=False))
            z.writestr("tags.json", json.dumps(tags_out, ensure_ascii=False))
            for im in images:
                if os.path.exists(im.path):
                    z.write(im.path, f"images/{im.id}.jpg")
        os.replace(tmp_path, zip_path)
    except Exception as e:
        _remove_file_safe(tmp_path)
        log_status("error", "backup", f"Бэкап проекта #{project_id} не удался: {e}")
        raise HTTPException(500, f"Бэкап не удался: {_safe_error_message(e)}")
    size = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0
    log_status("success", "backup",
               f"Бэкап проекта «{proj.name}» (id={project_id}, класс={meta['object_class']}): "
               f"{len(images)} фото, {size/1024/1024:.1f} МБ → {zip_name}")
    return {
        "status": "ok", "filename": zip_name, "path": zip_path, "size": size,
        "images_count": len(images), "tags_count": len(tags_out),
        "annotations_count": meta["annotations_count"],
    }

@app.get("/api/projects/{project_id}/backup/download/{filename}")
def download_backup(project_id: int, filename: str, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    if filename != os.path.basename(filename):
        raise HTTPException(400, "Некорректное имя файла")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Некорректное имя файла")
    if not filename.startswith(f"backup_project_{project_id}_"):
        raise HTTPException(400, "Файл не относится к этому проекту")
    if not filename.endswith(".zip"):
        raise HTTPException(400, "Ожидается .zip")
    path = os.path.join(BACKUP_DIR, filename)
    if os.path.islink(path):
        raise HTTPException(400, "Символические ссылки не поддерживаются")
    real = os.path.realpath(path)
    root = os.path.realpath(BACKUP_DIR)
    if not real.startswith(root + os.sep):
        raise HTTPException(400, {"key": "error.invalidPath", "fallback": "Некорректный путь"})
    if not os.path.exists(real):
        raise HTTPException(404, "Файл не найден")
    return FileResponse(real, filename=filename, media_type="application/zip")

# ---------------------------------------------------------------------------
# Экспорт
# ---------------------------------------------------------------------------
# [PATCH:STAGE1_LETTERBOX_HELPER]
def _build_letterbox_meta(images, fixed_size=FIXED_SIZE):
    """Метаданные letterbox-трансформации для каждого изображения.

    Возвращает dict {image_id_str: {filename, original_*, new_*, pad_*, scale}}.
    original_width/height берутся из колонок (появились в Stage 1),
    fallback на текущие (640×640), если для старых строк они NULL.
    """
    fw, fh = fixed_size
    out = {}
    for im in images:
        ow = getattr(im, "original_width", None)
        oh = getattr(im, "original_height", None)
        if not ow or not oh:
            ow = getattr(im, "width", None) or fw
            oh = getattr(im, "height", None) or fh
        try:
            ow = int(ow); oh = int(oh)
        except (TypeError, ValueError):
            ow, oh = fw, fh
        if ow <= 0 or oh <= 0:
            ow, oh = fw, fh
        scale = min(fw / ow, fh / oh)
        nw = ow * scale
        nh = oh * scale
        pad_x = (fw - nw) / 2.0
        pad_y = (fh - nh) / 2.0
        out[str(im.id)] = {
            "filename": im.filename,
            "original_width":  ow,
            "original_height": oh,
            "new_width":  int(fw),
            "new_height": int(fh),
            "pad_x": round(pad_x, 2),
            "pad_y": round(pad_y, 2),
            "scale": round(scale, 6),
            "transform_known": bool(getattr(im, "original_width", None)),
        }
    return out
# [/PATCH:STAGE1_LETTERBOX_HELPER]

    if not split_spec or split_spec == "none":
        return {"train": list(images), "val": [], "test": []}
    try:
        parts = [float(x) for x in split_spec.split(",")]
        if len(parts) == 2:
            parts.append(0.0)
        if len(parts) != 3:
            raise ValueError
        total = sum(parts)
        if total <= 0:
            raise ValueError
        parts = [p / total for p in parts]
    except (ValueError, AttributeError):
        return {"train": list(images), "val": [], "test": []}
    items = list(images)
    random.Random(42).shuffle(items)
    n = len(items)
    n_val = int(round(n * parts[1]))
    n_test = int(round(n * parts[2]))
    n_train = n - n_val - n_test
    if n_train < 0:
        deficit = -n_train
        if n_test >= deficit:
            n_test -= deficit
        else:
            deficit -= n_test
            n_test = 0
            n_val = max(0, n_val - deficit)
        n_train = 0
    end_train = n_train
    end_val = end_train + n_val
    end_test = end_val + n_test
    return {
        "train": items[:end_train],
        "val": items[end_train:end_val],
        "test": items[end_val:end_test],
    }

def _kp_name_to_index(schema=None) -> dict:
    """[FIX:v1341-backend] {имя: индекс} по переданной (или дефолтной) схеме."""
    if schema is None:
        schema = KEYPOINT_SCHEMA
    return {k[0]: i for i, k in enumerate(schema)}

def _kp_yolo_row(ann, kps_by_ann: dict, schema=None,
                 force_pad: bool = False) -> str:
    """[FIX:v1341-backend] YOLO-pose строка; schema — для кастомной схемы.

    force_pad=True — писать пустые точки нулями даже если их нет,
    чтобы строка соответствовала kpt_shape в data.yaml."""
    kps = kps_by_ann.get(ann.id) or []
    base = f"0 {ann.x:.6f} {ann.y:.6f} {ann.w:.6f} {ann.h:.6f}"
    if not kps and not force_pad:  # [FIX-STAGE2:POSE-PAD]
        return base
    if schema is None:
        schema = KEYPOINT_SCHEMA
    name2idx = _kp_name_to_index(schema)
    n = len(schema)
    arr = [None] * n  # (x, y, v)
    for kp in kps:
        idx = name2idx.get(kp.name)
        if idx is None:
            continue
        v = 1 if float(kp.visibility or 0) >= 0.5 else 0
        arr[idx] = (float(kp.x), float(kp.y), v)
    parts = [base]
    for item in arr:
        if item is None:
            parts.append("0.000000 0.000000 0")
        else:
            x, y, v = item
            parts.append(f"{x:.6f} {y:.6f} {v}")
    return " ".join(parts)

def _anns_with_keypoints(db, image_ids: list) -> dict:
    """V8.6.0: {annotation_id: [Keypoint, ...]}."""
    if not image_ids:
        return {}
    ann_ids = [row.id for row in db.query(Annotation.id)
                                 .filter(Annotation.image_id.in_(image_ids)).all()]
    if not ann_ids:
        return {}
    rows = (db.query(Keypoint)
              .filter(Keypoint.annotation_id.in_(ann_ids))
              .all())
    out = defaultdict(list)
    for kp in rows:
        out[kp.annotation_id].append(kp)
    return out

def _project_has_keypoints(db, project_id: int) -> bool:
    """V8.6.0: ≥50% аннотаций проекта имеют скелет."""
    total = (db.query(func.count(Annotation.id))
               .join(ImageModel, Annotation.image_id == ImageModel.id)
               .filter(ImageModel.project_id == project_id,
                       ImageModel.is_deleted.is_(False))
               .scalar() or 0)
    if total == 0:
        return False
    with_kp = (db.query(func.count(func.distinct(Keypoint.annotation_id)))
                 .join(Annotation, Annotation.id == Keypoint.annotation_id)
                 .join(ImageModel, Annotation.image_id == ImageModel.id)
                 .filter(ImageModel.project_id == project_id,
                         ImageModel.is_deleted.is_(False))
                 .scalar() or 0)
    return (with_kp / total) >= 0.5

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
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
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

        for bucket_name, bucket_images in buckets.items():
            if not bucket_images:
                continue
            sub_img = f"images/{bucket_name}" if use_split else "images"
            sub_lbl = f"labels/{bucket_name}" if use_split else "labels"
            for img in bucket_images:
                iname = _iname_for_export(img, naming, used)
                z.write(img.path, f"{sub_img}/{iname}")
                anns = db.query(Annotation).filter(Annotation.image_id == img.id).all()
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
                iname = _iname_for_export(img, naming, used)
                anns = db.query(Annotation).filter(Annotation.image_id == img.id).all()
                for ai, a in enumerate(anns):
                    kps = (db.query(Keypoint)
                             .filter(Keypoint.annotation_id == a.id)
                             .all())
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
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
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
                iname = _iname_for_export(img, naming, used)
                coco["images"].append({"id": img.id, "file_name": iname,
                                       "width": img.width, "height": img.height})
                anns = db.query(Annotation).filter(Annotation.image_id == img.id).all()
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
                        n = len(KEYPOINT_SCHEMA)
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

@app.get("/api/storage/info")
def storage_info(db: Session = Depends(get_db)):
    info = {
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
    info["total_size"] = sum(info["dirs"].values())
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

@app.get("/api/storage/paths")
def storage_paths():
    return {
        "data_root": DATA_ROOT, "uploads": UPLOAD_DIR, "thumbnails": THUMB_DIR,
        "models": MODEL_DIR, "videos": VIDEO_DIR, "backups": BACKUP_DIR,
    }

@app.post("/api/storage/backup_db")
def storage_backup_db():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if DB_ENGINE == "sqlite":
        db_path = str(engine.url).replace("sqlite:///", "")
        if not os.path.exists(db_path):
            raise HTTPException(404, "Файл БД не найден")
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

@app.get("/api/storage/migrate/status")
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

@app.post("/api/storage/migrate/start")
def migrate_start(payload: MigrateIn = Body(default_factory=MigrateIn)):
    global MIGRATE_THREAD
    if DB_ENGINE != "mysql":
        raise HTTPException(400, "Миграция возможна только при DB_ENGINE=mysql")
    with MIGRATE_LOCK:
        if MIGRATE_STATE["status"] == "running":
            raise HTTPException(409, "Миграция уже идёт")
    target = (payload.target_path or "").strip()
    if not target:
        target = _sqlite_target_path()
    target = os.path.abspath(target)
    if target.startswith(os.path.join(DATA_ROOT, "uploads")) or \
       target.startswith(os.path.join(DATA_ROOT, "thumbs")):
        raise HTTPException(400, "Нельзя класть БД внутрь uploads/ или thumbs/")
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

@app.post("/api/storage/migrate/reset")
def migrate_reset():
    with MIGRATE_LOCK:
        if MIGRATE_STATE["status"] == "running":
            raise HTTPException(409, "Миграция идёт")
        MIGRATE_STATE.update({
            "status": "idle", "stage": "", "message": "", "progress": 0.0,
            "stats": {}, "target_path": "", "env_updated": False,
            "started_at": None, "finished_at": None, "error": None,
        })
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# FFmpeg endpoints
# ---------------------------------------------------------------------------
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
def _backfill_v760():
    try:
        db = SessionLocal()
        try:
            flag = db.query(Setting).filter(Setting.key == SETTING_BACKFILL_DONE).first()
            if flag and flag.value == "1":
                return
            rows = db.query(ImageModel).filter(
                (ImageModel.created_at.is_(None)) | (ImageModel.file_size.is_(None))
            ).all()
            n = 0
            for r in rows:
                if r.created_at is None:
                    try:
                        r.created_at = datetime.fromtimestamp(os.path.getmtime(r.path))
                    except OSError:
                        r.created_at = utcnow()
                if r.file_size is None:
                    try:
                        r.file_size = os.path.getsize(r.path)
                    except OSError:
                        r.file_size = 0
                n += 1
                if n % 200 == 0:
                    db.commit()
            db.commit()
            set_setting(db, SETTING_BACKFILL_DONE, "1")
            if n:
                log.info("backfill v7.6.0: обновлено %d записей", n)
        finally:
            db.close()
    except Exception:
        log.exception("backfill v7.6.0 failed")

# V7.9.3: _backfill_v760() вызывается в lifespan (в фоне),
# чтобы импорт модуля не блокировался на больших датасетах.



# [STAGE1-A:validator]
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
    password: str = ""
    role: str = "annotator"


def _hash_password_simple(pw: str) -> str:
    """[PATCH:STAGE2_3] Placeholder hash — swap for bcrypt/argon2 in production."""
    if not pw:
        return ""
    import hashlib as _hl
    return _hl.sha256(pw.encode("utf-8")).hexdigest()


def require_role(*allowed_roles):
    """[PATCH:STAGE2_3] Dependency factory for role checks.

    Usage:
        @app.get("/api/foo", dependencies=[Depends(require_role("admin"))])
    """
    def _checker():
        # Placeholder: no real auth yet. Return admin so admin-only UI works.
        return {"role": "admin", "username": "admin"}
    return _checker




@app.get("/api/users")
def list_users(db: Session = Depends(get_db)):
    from models import User
    rows = db.query(User).order_by(User.id).all()
    return {"items": [
        {"id": u.id, "username": u.username, "role": u.role,
         "is_active": bool(u.is_active),
         "created_at": u.created_at.isoformat() if u.created_at else None}
        for u in rows
    ]}


@app.post("/api/users")
def create_user(payload: UserIn, db: Session = Depends(get_db)):
    from models import User
    username = (payload.username or "").strip()
    if not username:
        raise HTTPException(400, "username is required")
    if payload.role not in ("admin", "cv_engineer", "annotator"):
        raise HTTPException(400, "role must be one of: admin, cv_engineer, annotator")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "username already exists")
    u = User(
        username=username,
        password_hash=_hash_password_simple(payload.password),
        role=payload.role,
        is_active=1,
        created_at=utcnow(),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    log_status("info", "system",
               f"RBAC: user {username} ({payload.role}) created")
    return {"id": u.id, "username": u.username, "role": u.role}


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    from models import User, UserProjectAccess
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    db.query(UserProjectAccess) \
        .filter(UserProjectAccess.user_id == user_id) \
        .delete(synchronize_session=False)
    db.delete(u)
    db.commit()
    log_status("warning", "system", f"RBAC: user {u.username} deleted")
    return {"status": "ok"}
# [/PATCH:STAGE2_3:rbac-endpoints]

# [PATCH:STAGE3_1:endpoints]
class ValidateBehaviorIn(BaseModel):
    image_id: int
    true_behavior: str
    annotation_id: Optional[int] = None
    validated_by: Optional[str] = None


_VALID_BEHAVIORS = {"eat", "walk", "lie", "drink", "stand", "active"}


@app.post("/api/projects/{project_id}/validate_behavior")
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


@app.get("/api/projects/{project_id}/agreement_score")
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
@app.get("/api/models/{name}/edge_package")
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

@app.get("/api/auth/me")
def api_auth_me(request: Request, db: Session = Depends(get_db)):
    from models import User
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        u = db.query(User).filter(User.username == auth[7:]).first()
        if u: return {"username": u.username, "role": u.role}
    return {"username": "admin", "role": "admin"}

@app.post("/api/auth/login")
def api_auth_login(payload: dict = Body(...), db: Session = Depends(get_db)):
    from models import User
    import hashlib
    u = payload.get('username')
    p = payload.get('password')
    if not u: raise HTTPException(400, "Username required")
    user = db.query(User).filter(User.username == u).first()
    if not user:
        raise HTTPException(401, "Неверный логин или пароль")
    if user.password_hash:
        h = hashlib.sha256(p.encode('utf-8')).hexdigest()
        if h != user.password_hash:
            raise HTTPException(401, "Неверный логин или пароль")
    return {"token": user.username, "user": {"username": user.username, "role": user.role}}


@app.get("/api/projects/{project_id}/versions/diff_extended")
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
    return {
        "images_added": max(0, img_count - v1_img),
        "images_removed": max(0, v1_img - img_count),
        "annotations_added": max(0, ann_count - v1_ann),
        "annotations_removed": max(0, v1_ann - ann_count),
        "keypoints_added": kp_count,
        "behaviors_added": beh_count,
        "is_identical": False
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

# [STAGE13:app-refactor]

# [FIX:v1341-backend]
