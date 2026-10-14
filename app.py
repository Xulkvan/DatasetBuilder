"""
Dataset Builder — V8.2.3
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
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, Response, JSONResponse
from pydantic import BaseModel, Field, field_validator
from PIL import Image

Image.MAX_IMAGE_PIXELS = 50_000_000

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, ForeignKey,
    Boolean, DateTime, inspect, text, UniqueConstraint, Index, func, case,
    or_, and_
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from sqlalchemy import event as _sa_event

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

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

try:
    warnings.simplefilter('error', Image.DecompressionBombWarning)
except Exception:
    pass

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------
APP_VERSION = "V8.2.3"
AUTHOR = "Xulkvan"

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
SETTING_SAM_MODEL = "sam_model_name"
SETTING_DEFAULT_EXTRACT_FPS = "default_extract_fps"
SETTING_BACKFILL_DONE = "backfill_v760_done"
SETTING_FFMPEG_PATH = "ffmpeg_path"  # V7.6.2

DEFAULT_SAM_MODEL = "mobile_sam.pt"
VALID_SAM_MODELS = ("mobile_sam.pt", "sam2_t.pt", "sam2_s.pt", "sam2_b.pt", "FastSAM-s.pt")
SAM_MIN_POINTS = 1
SAM_MAX_POINTS = 8
ACTIVE_LEARNING_NEW_THRESHOLD = 30

DEFAULT_OBJECT_CLASS = "pig"
MAX_OBJECT_CLASS_LEN = 128

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

INVALID_CHARS_RE = re.compile(r'[\\/:*?"<>|]')
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
_EPOCH_RE = re.compile(r'^\s*(\d+)/(\d+)\s+\d+(?:\.\d+)?G\s')
_MODEL_NAME_RE = re.compile(r'^[A-Za-z0-9_\-\.\(\) ]+\.pt$')
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".webp",
    ".tif", ".tiff", ".avif", ".heic", ".heif", ".gif",
})

YOLO_RELEASE_TAG = "v8.3.0"
YOLO_URL_TEMPLATE = "https://github.com/ultralytics/assets/releases/download/{tag}/{name}"

for d in (UPLOAD_DIR, EXPORT_DIR, MODEL_DIR, IMPORT_DIR, RUNS_DIR, THUMB_DIR, BACKUP_DIR, VIDEO_DIR, DATA_DIR):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# In-memory status log
# ---------------------------------------------------------------------------
STATUS_LOG = deque(maxlen=1000)
STATUS_LOG_LOCK = threading.Lock()

_USER_PATH_RE = [
    (re.compile(r'/Users/[^/\s]+'), '/Users/<user>'),
    (re.compile(r'/home/[^/\s]+'), '/home/<user>'),
    (re.compile(r'C:\\Users\\[^\\\s]+'), r'C:\\Users\\<user>'),
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

# ---------------------------------------------------------------------------
# MySQL / SQLite
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB_ENGINE = os.getenv("DB_ENGINE", "mysql").strip().lower()
if DB_ENGINE not in ("mysql", "sqlite"):
    log.warning("DB_ENGINE=%r неизвестен, использую 'mysql'", DB_ENGINE)
    DB_ENGINE = "mysql"

if DB_ENGINE == "sqlite":
    DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "dataset.db"))
    DB_PATH = os.path.abspath(DB_PATH)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    DATABASE_URL = f"sqlite:///{DB_PATH}"

    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30.0},
        pool_pre_ping=True,
    )

    @_sa_event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):
        try:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA cache_size=-20000")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()
        except Exception:
            log.exception("sqlite pragma setup failed")

    log.info("Хранилище: SQLite — %s", DB_PATH)
    if not os.path.exists(DB_PATH):
        log.info("Файл БД не найден — создаю новый")
else:
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "root")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "3306")
    DB_NAME = os.getenv("DB_NAME", "pig_dataset")

    DATABASE_URL = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        f"?charset=utf8mb4"
    )

    engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True,
                           pool_size=10, max_overflow=20)
    log.info("Хранилище: MySQL — %s:%s/%s", DB_HOST, DB_PORT, DB_NAME)

    if DB_PASSWORD == "root":
        log.warning("Используется пароль MySQL по умолчанию 'root'. "
                    "Задай DB_PASSWORD через переменную окружения или .env.")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# ---------------------------------------------------------------------------
# ORM
# ---------------------------------------------------------------------------
class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False, server_default="0")
    deleted_at = Column(DateTime, nullable=True)
    object_class = Column(String(128), nullable=False, default=DEFAULT_OBJECT_CLASS,
                          server_default=DEFAULT_OBJECT_CLASS)
    object_class_source = Column(String(16), nullable=False, default="list",
                                 server_default="list")
    trash_ttl_days_override = Column(Integer, nullable=True)
    thumbnail_size = Column(Integer, nullable=True)
    default_zoom = Column(Float, nullable=True)
    images = relationship("ImageModel", back_populates="project", cascade="all, delete-orphan")
    tags = relationship("Tag", back_populates="project", cascade="all, delete-orphan")
    __table_args__ = (
        Index('ix_projects_deleted', 'is_deleted', 'deleted_at'),
    )

class ImageModel(Base):
    __tablename__ = "images"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    path = Column(String(512), nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    is_deleted = Column(Boolean, nullable=False, default=False, server_default="0")
    deleted_at = Column(DateTime, nullable=True)
    phash = Column(String(16), nullable=True)
    is_hard = Column(Boolean, nullable=False, default=False, server_default="0")
    video_id = Column(Integer, nullable=True, index=True)
    frame_index = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=True)
    file_size = Column(Integer, nullable=True)
    project = relationship("Project", back_populates="images")
    annotations = relationship("Annotation", back_populates="image", cascade="all, delete-orphan")
    tags = relationship("ImageTag", back_populates="image", cascade="all, delete-orphan")
    __table_args__ = (
        Index('ix_images_proj_deleted', 'project_id', 'is_deleted'),
        Index('ix_images_deleted_at', 'is_deleted', 'deleted_at'),
        Index('ix_images_phash', 'project_id', 'phash'),
    )

class Annotation(Base):
    __tablename__ = "annotations"
    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    w = Column(Float, nullable=False)
    h = Column(Float, nullable=False)
    label = Column(String(64), nullable=False, default=DEFAULT_OBJECT_CLASS)
    confidence = Column(Float, nullable=True)
    is_frozen = Column(Boolean, nullable=False, default=False, server_default="0")
    image = relationship("ImageModel", back_populates="annotations")

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(64), primary_key=True)
    value = Column(String(255), nullable=False)

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    color = Column(String(7), nullable=True)
    __table_args__ = (UniqueConstraint('project_id', 'name', name='uq_project_tag'),)
    project = relationship("Project", back_populates="tags")

class ImageTag(Base):
    __tablename__ = "image_tags"
    image_id = Column(Integer, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True)
    image = relationship("ImageModel", back_populates="tags")

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    path = Column(String(512), nullable=False)
    fps = Column(Float, nullable=True)
    frame_count = Column(Integer, nullable=True)
    duration_sec = Column(Float, nullable=True)
    extract_fps = Column(Float, nullable=True)
    images_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False, server_default="0")
    deleted_at = Column(DateTime, nullable=True)
    __table_args__ = (
        Index('ix_videos_project', 'project_id', 'is_deleted'),
    )

# ---------------------------------------------------------------------------
# Pydantic схемы
# ---------------------------------------------------------------------------
class AnnotationIn(BaseModel):
    x: float
    y: float
    w: float
    h: float
    label: str = DEFAULT_OBJECT_CLASS
    confidence: Optional[float] = None
    frozen: bool = False

    @field_validator('x', 'y', 'w', 'h')
    @classmethod
    def _clamp(cls, v):
        return max(0.0, min(1.0, float(v)))

    @field_validator('confidence')
    @classmethod
    def _clamp_conf(cls, v):
        if v is None:
            return None
        return max(0.0, min(1.0, float(v)))

    @field_validator('label')
    @classmethod
    def _label_len(cls, v):
        v = (v or DEFAULT_OBJECT_CLASS)[:64]
        return v or DEFAULT_OBJECT_CLASS

class BatchAutolabelIn(BaseModel):
    image_ids: list[int] = Field(default_factory=list)
    project_id: Optional[int] = None
    tta: bool = False          # V8.1.0: test-time augmentation
    mode: str = "add"          # V8.2.0: "add" | "replace"


class AutolabelIn(BaseModel):
    tta: bool = False          # V8.1.0
    mode: str = "add"          # V8.2.0: "add" | "replace"


def _norm_mode(m: str) -> str:
    """V8.2.0: нормализация режима авторазметки."""
    return m if m in ("add", "replace") else "add"

class DownloadModelIn(BaseModel):
    size: str = "n"
    pretrain: str = "oiv7"
    custom_name: str = ""

class BatchTagsIn(BaseModel):
    image_ids: list[int] = Field(default_factory=list)
    add: list[int] = Field(default_factory=list)
    remove: list[int] = Field(default_factory=list)

class ProjectSettingsIn(BaseModel):
    object_class: Optional[str] = None
    object_class_source: Optional[str] = None
    trash_ttl_days_override: Optional[int] = None
    thumbnail_size: Optional[int] = None
    default_zoom: Optional[float] = None
    clear_ttl_override: bool = False
    clear_thumbnail_size: bool = False
    clear_default_zoom: bool = False

class SamPoint(BaseModel):
    x: float
    y: float
    positive: bool = True

class SamPredictIn(BaseModel):
    points: list[SamPoint] = Field(default_factory=list)

class MigrateIn(BaseModel):
    target_path: Optional[str] = None
    overwrite: bool = False

class ImportRoboflowIn(BaseModel):
    api_key: str
    workspace: str
    project: str
    version: int

class ImportSuperviselyIn(BaseModel):
    api_token: str
    project_id: int
    dataset_id: Optional[int] = None

class ImportUrlIn(BaseModel):
    url: str
    filename: Optional[str] = None

class ImportLocalFolderIn(BaseModel):
    path: str
    recursive: bool = True

class ImportLabelboxIn(BaseModel):
    api_key: str
    project_id: str

class ImportScaleIn(BaseModel):
    api_key: str
    dataset_id: str

class ImportDarwinIn(BaseModel):
    api_key: str
    team_slug: str
    dataset_slug: str
    version_name: Optional[str] = None

class BulkRenameIn(BaseModel):
    image_ids: list[int]
    pattern: str = "image_{n:04d}"
    start: int = 1

class BulkMoveCopyIn(BaseModel):
    image_ids: list[int]
    target_project_id: int
    copy_files: bool = False

class FfmpegPathIn(BaseModel):
    path: str = ""

# ---------------------------------------------------------------------------
# Миграции
# ---------------------------------------------------------------------------
_MIGRATIONS = [
    ("images", "is_deleted", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("images", "deleted_at", "DATETIME NULL"),
    ("images", "phash", "VARCHAR(16) NULL"),
    ("images", "is_hard", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("annotations", "confidence", "FLOAT NULL"),
    ("annotations", "is_frozen", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("projects", "created_at", "DATETIME NULL"),
    ("projects", "is_deleted", "TINYINT(1) NOT NULL DEFAULT 0"),
    ("projects", "deleted_at", "DATETIME NULL"),
    ("projects", "object_class", f"VARCHAR(128) NOT NULL DEFAULT '{DEFAULT_OBJECT_CLASS}'"),
    ("projects", "object_class_source", "VARCHAR(16) NOT NULL DEFAULT 'list'"),
    ("projects", "trash_ttl_days_override", "INT NULL"),
    ("projects", "thumbnail_size", "INT NULL"),
    ("projects", "default_zoom", "FLOAT NULL"),
    ("images", "video_id", "INT NULL"),
    ("images", "frame_index", "INT NULL"),
    ("images", "created_at", "DATETIME NULL"),
    ("images", "file_size", "INT NULL"),
]

def ensure_schema():
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
            log.exception("ensure_schema: cannot read columns for %s", table)
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
            if DB_ENGINE == "sqlite":
                log.warning("migrate: %s.%s skipped (%s)", table, column, e)
            else:
                log.exception("migrate: %s.%s failed", table, column)

    try:
        inspector = inspect(engine)
        if "projects" in inspector.get_table_names():
            idx_names = {ix["name"] for ix in inspector.get_indexes("projects")}
            if "ix_projects_deleted" not in idx_names:
                with engine.begin() as conn:
                    conn.execute(text(
                        "CREATE INDEX ix_projects_deleted ON projects (is_deleted, deleted_at)"
                    ))
                log.info("migrate: ix_projects_deleted added")
    except Exception:
        log.exception("migrate: projects index failed")

    if DB_ENGINE == "sqlite":
        try:
            insp = inspect(engine)
            tables = set(insp.get_table_names())
            wanted = {
                "images": [("ix_images_proj_deleted", "project_id, is_deleted")],
                "videos": [("ix_videos_project", "project_id, is_deleted")],
            }
            for tname, idxs in wanted.items():
                if tname not in tables:
                    continue
                have = {ix["name"] for ix in insp.get_indexes(tname)}
                for iname, cols in idxs:
                    if iname in have:
                        continue
                    try:
                        with engine.begin() as conn:
                            conn.execute(text(f'CREATE INDEX {iname} ON {tname} ({cols})'))
                        log.info("migrate: %s added", iname)
                    except Exception:
                        log.exception("migrate: %s failed", iname)
        except Exception:
            log.exception("sqlite index check failed")

ensure_schema()
Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------
def get_setting(db, key, default):
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else default

def set_setting(db, key, value):
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = str(value)
    else:
        db.add(Setting(key=key, value=str(value)))
    db.commit()

def get_trash_ttl_days(db) -> int:
    try:
        return int(get_setting(db, SETTING_TRASH_TTL, DEFAULT_TRASH_TTL_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_TRASH_TTL_DAYS

def _validate_color(c: str) -> str:
    c = (c or "").strip()
    if not _HEX_COLOR_RE.match(c):
        log.warning("invalid color %r, using default", c)
        return "#0071e3"
    return c.lower()

def _is_simple_filename(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    if ".." in name or "/" in name or "\\" in name:
        return False
    if "\x00" in name:
        return False
    return True

def _safe_model_path(name: str) -> str:
    if not _is_simple_filename(name):
        raise HTTPException(400, {"key": "error.invalidModelName", "fallback": "Некорректное имя модели"})
    if not _MODEL_NAME_RE.match(name):
        raise HTTPException(400, {"key": "error.invalidModelName", "fallback": "Некорректное имя модели"})
    p = os.path.join(MODEL_DIR, name)
    if os.path.islink(p):
        raise HTTPException(400, "Символические ссылки не поддерживаются")
    real = os.path.realpath(p)
    root = os.path.realpath(MODEL_DIR)
    if not (real == root or real.startswith(root + os.sep)):
        raise HTTPException(400, "Некорректный путь к модели")
    return real

def _sanitize_model_name(name: str) -> str:
    if not name:
        return ""
    base = re.sub(r'[^A-Za-z0-9_\-\. ]', '_', name.strip())
    base = base.strip('._-')
    if not base:
        return ""
    if not base.lower().endswith(".pt"):
        base += ".pt"
    if len(base) > 200:
        base = base[:196] + ".pt"
    if not _is_simple_filename(base):
        return ""
    if not _MODEL_NAME_RE.match(base):
        return ""
    return base

def _unique_model_name_from_disk(name: str) -> str:
    existing = set()
    if os.path.isdir(MODEL_DIR):
        existing = {f for f in os.listdir(MODEL_DIR) if f.endswith(".pt")}
    if name not in existing:
        return name
    stem = name[:-3] if name.lower().endswith(".pt") else name
    n = 1
    while f"{stem} ({n}).pt" in existing:
        n += 1
    return f"{stem} ({n}).pt"

def get_active_model_path(db):
    name = get_setting(db, SETTING_ACTIVE_MODEL, "")
    if name:
        try:
            p = _safe_model_path(name)
            if os.path.exists(p):
                return p
        except HTTPException:
            log.debug("active model %r not accessible", name)
        except Exception:
            log.exception("unexpected error checking active model %r", name)

    default_path = os.path.join(MODEL_DIR, "pig.pt")
    if os.path.exists(default_path):
        return default_path

    if os.path.isdir(MODEL_DIR):
        for f in sorted(os.listdir(MODEL_DIR)):
            if f.endswith(".pt"):
                return os.path.join(MODEL_DIR, f)
    return None

def _remove_file_safe(p: str):
    if not p:
        return
    try:
        real = os.path.realpath(p)
        if not real.startswith(os.path.realpath(DATA_ROOT) + os.sep):
            log.debug("skip removal outside data root: %s", p)
            return
        if os.path.isfile(real):
            os.remove(real)
    except OSError as e:
        log.warning("cannot remove %s: %s", p, e)
    except Exception:
        log.exception("unexpected error removing %s", p)

# ---------------------------------------------------------------------------
# object_class helpers
# ---------------------------------------------------------------------------
def _validate_object_class(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise HTTPException(400, "Имя класса не может быть пустым")
    if len(n) > MAX_OBJECT_CLASS_LEN:
        raise HTTPException(400, f"Слишком длинное имя класса (макс. {MAX_OBJECT_CLASS_LEN})")
    if not re.match(r"^[\w\s\-\.'\(\)/]+$", n, flags=re.UNICODE):
        raise HTTPException(400, "Недопустимые символы в имени класса")
    return n

def _validate_object_class_source(src: str) -> str:
    s = (src or "").strip().lower()
    if s not in ("list", "custom"):
        return "list"
    return s

def _resolve_target_class_ids(model, object_class: str) -> set:
    names = getattr(model, "names", {}) or {}
    target = (object_class or "").strip().lower()
    if not target:
        return set()
    out = set()
    for cid, cname in names.items():
        try:
            cn = str(cname).strip().lower()
        except Exception:
            continue
        if cn == target:
            try:
                out.add(int(cid))
            except (TypeError, ValueError):
                continue
    return out

def _read_model_class_names(model) -> list:
    names = getattr(model, "names", {}) or {}
    result = []
    for cid, cname in names.items():
        try:
            cn = str(cname).strip()
        except Exception:
            continue
        if cn:
            result.append(cn)
    seen = set()
    unique = []
    for n in result:
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(n)
    unique.sort(key=lambda s: s.lower())
    return unique

# ---------------------------------------------------------------------------
# Модель-класс-совместимость
# ---------------------------------------------------------------------------
_MODEL_CLASSES_CACHE: dict = {}
_MODEL_CLASSES_LOCK = threading.Lock()

def _get_model_classes_cached(model_name: str) -> Optional[set]:
    with _MODEL_CLASSES_LOCK:
        if model_name in _MODEL_CLASSES_CACHE:
            return _MODEL_CLASSES_CACHE[model_name]
    try:
        path = _safe_model_path(model_name)
    except HTTPException:
        return None
    if not os.path.exists(path):
        return None
    try:
        from ultralytics import YOLO
        m = YOLO(path)
        names = getattr(m, "names", {}) or {}
        classes = set()
        for _, v in names.items():
            try:
                classes.add(str(v).strip().lower())
            except Exception:
                continue
        with _MODEL_CLASSES_LOCK:
            _MODEL_CLASSES_CACHE[model_name] = classes
        try:
            del m
        except Exception:
            pass
        gc.collect()
        return classes
    except Exception:
        log.exception("load model classes failed: %s", model_name)
        return None

def _invalidate_model_classes_cache(name: Optional[str] = None):
    with _MODEL_CLASSES_LOCK:
        if name is None:
            _MODEL_CLASSES_CACHE.clear()
        else:
            _MODEL_CLASSES_CACHE.pop(name, None)

# ---------------------------------------------------------------------------
# SAM
# ---------------------------------------------------------------------------
_SAM_CACHE = {}
_SAM_CACHE_LOCK = threading.Lock()
# V7.9.0: ключ последней картинки, чей эмбеддинг уже посчитан.
_SAM_LAST_IMAGE_KEY = None

def get_sam_model_name(db) -> str:
    name = get_setting(db, SETTING_SAM_MODEL, DEFAULT_SAM_MODEL)
    if name not in VALID_SAM_MODELS:
        name = DEFAULT_SAM_MODEL
    return name

def _get_sam_model(model_name: str):
    with _SAM_CACHE_LOCK:
        m = _SAM_CACHE.get(model_name)
        if m is not None:
            return m
    from ultralytics import SAM
    m = SAM(model_name)
    with _SAM_CACHE_LOCK:
        _SAM_CACHE.clear()
        _SAM_CACHE[model_name] = m
    return m

def _clear_sam_cache():
    global _SAM_LAST_IMAGE_KEY
    with _SAM_CACHE_LOCK:
        old = list(_SAM_CACHE.values())
        _SAM_CACHE.clear()
    for m in old:
        try:
            del m
        except Exception:
            pass
    try:
        gc.collect()
    except Exception:
        pass

    _SAM_LAST_IMAGE_KEY = None

def _bbox_from_mask_np(mask_np):
    if not _HAS_NUMPY:
        return None
    try:
        rows = _np.any(mask_np, axis=1)
        cols = _np.any(mask_np, axis=0)
        if not rows.any() or not cols.any():
            return None
        ys = _np.where(rows)[0]
        xs = _np.where(cols)[0]
        return float(xs[0]), float(ys[0]), float(xs[-1] + 1), float(ys[-1] + 1)
    except Exception:
        return None

def _extract_sam_result(r):
    """Вытаскивает bbox_px, score и b64-маску из результата SAM."""
    mask_np = None
    try:
        if getattr(r, "masks", None) is not None and len(r.masks.data) > 0:
            mask_np = r.masks.data[0].cpu().numpy()
    except Exception:
        log.exception("SAM mask extraction failed")

    bbox_px = None
    if mask_np is not None:
        bbox_px = _bbox_from_mask_np(mask_np)

    if bbox_px is None and getattr(r, "boxes", None) is not None and len(r.boxes) > 0:
        try:
            xyxy = r.boxes.xyxy.cpu().numpy()
            if len(xyxy) > 0:
                x1, y1, x2, y2 = xyxy[0].tolist()
                bbox_px = (float(x1), float(y1), float(x2), float(y2))
        except Exception:
            log.exception("SAM bbox fallback failed")

    if bbox_px is None:
        return None

    score = 1.0
    try:
        if getattr(r, "boxes", None) is not None and getattr(r.boxes, "conf", None) is not None:
            cf = r.boxes.conf.cpu().numpy()
            if len(cf) > 0:
                score = float(cf[0])
    except Exception:
        pass

    mask_b64 = ""
    if mask_np is not None:
        try:
            small = Image.fromarray((mask_np > 0.5).astype("uint8") * 255)
            small = small.resize((160, 160), Image.Resampling.NEAREST)
            buf = io.BytesIO()
            small.save(buf, format="PNG", optimize=True)
            mask_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            log.exception("SAM mask encode failed")
    return {"bbox_px": bbox_px, "score": score, "mask_b64": mask_b64}


def _run_sam_predict(model, img_path: str, points_px: list, labels: list):
    """Первый клик по картинке — encoder+decoder. Следующие — только decoder."""
    global _SAM_LAST_IMAGE_KEY

    # Быстрый путь: эмбеддинг этой же картинки уже в predictor.
    if _SAM_LAST_IMAGE_KEY == img_path:
        predictor = getattr(model, "predictor", None)
        if predictor is not None:
            try:
                results = predictor(points=points_px, labels=labels)
                if results:
                    res = _extract_sam_result(results[0])
                    if res:
                        return res
            except Exception:
                log.exception("SAM cached predict failed, falling back to full path")
                _SAM_LAST_IMAGE_KEY = None

    # Полный путь: encoder + decoder (~1–2 с на CPU).
    results = model(img_path, points=points_px, labels=labels, verbose=False)
    if not results:
        return None
    # После этого вызова predictor содержит эмбеддинг этой картинки.
    _SAM_LAST_IMAGE_KEY = img_path
    return _extract_sam_result(results[0])

# ---------------------------------------------------------------------------
# Training metadata
# ---------------------------------------------------------------------------
def _save_training_metadata(run_dir: str, project_id: int, object_class: str,
                             model_name: str, epochs: int, imgsz: int,
                             annotated_count: int):
    results_csv = os.path.join(run_dir, "output", "train", "results.csv")
    summary = _summarize_training_results(results_csv)
    run_id = os.path.basename(run_dir).replace("train_", "")
    meta = {
        "run_id": run_id,
        "created_at": utcnow().isoformat(),
        "project_id": project_id,
        "object_class": object_class,
        "model_name": model_name,
        "epochs": epochs,
        "imgsz": imgsz,
        "annotated_count": annotated_count,
        "summary": summary,
    }
    try:
        with open(os.path.join(run_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        log.exception("save training metadata failed")
    return meta

def _summarize_training_results(results_csv: str):
    if not os.path.exists(results_csv):
        return {}
    try:
        with open(results_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                if not clean.get("epoch"):
                    continue
                rows.append(clean)
    except Exception:
        log.exception("parse results.csv failed")
        return {}
    if not rows:
        return {}

    def _f(row, key, default=0.0):
        try:
            return float(row.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    best = None
    best_val = -1.0
    for r in rows:
        v = _f(r, "metrics/mAP50-95(B)", 0.0)
        if v > best_val:
            best_val = v
            best = r
    if best is None:
        return {}
    return {
        "best_epoch": int(_f(best, "epoch", 0)),
        "mAP50": _f(best, "metrics/mAP50(B)", 0.0),
        "mAP50_95": _f(best, "metrics/mAP50-95(B)", 0.0),
        "precision": _f(best, "metrics/precision(B)", 0.0),
        "recall": _f(best, "metrics/recall(B)", 0.0),
        "total_epochs": len(rows),
    }

# ---------------------------------------------------------------------------
# FFmpeg
# ---------------------------------------------------------------------------
_FFMPEG_PATHS = {"ok": False, "ffmpeg": "ffmpeg", "ffprobe": "ffprobe", "source": ""}
_FFMPEG_LOCK = threading.Lock()

def _resolve_ffmpeg():
    try:
        db = SessionLocal()
        try:
            custom = get_setting(db, SETTING_FFMPEG_PATH, "")
        finally:
            db.close()
        if custom and os.path.isfile(custom):
            ff_dir = os.path.dirname(custom)
            fp_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
            ffprobe = os.path.join(ff_dir, fp_name)
            return True, custom, (ffprobe if os.path.isfile(ffprobe) else ""), "setting"
    except Exception:
        log.exception("resolve ffmpeg: settings check failed")

    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")
    if ff and fp:
        return True, ff, fp, "path"
    if ff:
        return True, ff, "", "path"

    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
        candidates = [
            # V7.8.1: стандартные места WinGet
            os.path.join(local_appdata, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
            # классические ручные установки
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe"),
        ]
        # V7.8.1: любые Gyan.FFmpeg_*/ffmpeg-*/bin/ffmpeg.exe, поставленные через WinGet
        try:
            pkg_root = os.path.join(local_appdata, "Microsoft", "WinGet", "Packages")
            if os.path.isdir(pkg_root):
                for name in os.listdir(pkg_root):
                    if name.lower().startswith("gyan.ffmpeg"):
                        inner = os.path.join(pkg_root, name)
                        try:
                            for sub in os.listdir(inner):
                                cand = os.path.join(inner, sub, "bin", "ffmpeg.exe")
                                if os.path.isfile(cand):
                                    candidates.insert(0, cand)
                        except OSError:
                            continue
        except OSError:
            pass
    else:
        candidates = [
            "/usr/local/bin/ffmpeg",
            "/opt/homebrew/bin/ffmpeg",
            "/usr/bin/ffmpeg",
            "/snap/bin/ffmpeg",
            os.path.expanduser("~/.local/bin/ffmpeg"),
        ]
    for c in candidates:
        if os.path.isfile(c):
            fp_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
            ffprobe = os.path.join(os.path.dirname(c), fp_name)
            return True, c, (ffprobe if os.path.isfile(ffprobe) else ""), "common"

    return False, "", "", ""

def _check_ffmpeg() -> tuple:
    ok, ff, fp, src = _resolve_ffmpeg()
    with _FFMPEG_LOCK:
        _FFMPEG_PATHS["ok"] = bool(ok and ff and fp)
        _FFMPEG_PATHS["ffmpeg"] = ff or "ffmpeg"
        _FFMPEG_PATHS["ffprobe"] = fp or "ffprobe"
        _FFMPEG_PATHS["source"] = src
    if not ok or not ff:
        return False, "ffmpeg не найден"
    if not fp:
        return False, "ffprobe не найден рядом с ffmpeg"
    return True, ""

def _probe_video(path: str) -> Optional[dict]:
    try:
        r = subprocess.run(
            [_FFMPEG_PATHS["ffprobe"], "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate,nb_frames,duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30,
            creationflags=_SUBPROC_FLAGS,
        )
        if r.returncode != 0:
            log.warning("ffprobe failed: %s", (r.stderr or "")[:300])
            return None
        data = json.loads(r.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return None
        s = streams[0]
        fps_str = str(s.get("r_frame_rate") or "0/1")
        if "/" in fps_str:
            num, den = fps_str.split("/", 1)
            try:
                fps = (float(num) / float(den)) if float(den) else 0.0
            except (TypeError, ValueError):
                fps = 0.0
        else:
            try:
                fps = float(fps_str)
            except ValueError:
                fps = 0.0
        try:
            duration = float(s.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        try:
            frame_count = int(s.get("nb_frames") or 0)
        except (TypeError, ValueError):
            frame_count = 0
        if not frame_count and fps and duration:
            frame_count = int(round(fps * duration))
        return {"fps": fps, "duration": duration, "frame_count": frame_count}
    except Exception:
        log.exception("probe video failed")
        return None

def _extract_frames(video_path: str, out_dir: str, fps: float) -> list:
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "frame_%06d.jpg")
    cmd = [
        _FFMPEG_PATHS["ffmpeg"], "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-vf", f"fps={fps}",
        "-q:v", "3",
        pattern,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, creationflags=_SUBPROC_FLAGS)
        if r.returncode != 0:
            log.warning("ffmpeg extract failed: %s", (r.stderr or "")[:300])
            return []
    except subprocess.TimeoutExpired:
        log.error("ffmpeg extract timeout")
        return []
    except Exception:
        log.exception("extract frames failed")
        return []
    files = sorted(
        os.path.join(out_dir, f)
        for f in os.listdir(out_dir)
        if f.startswith("frame_") and f.endswith(".jpg")
    )
    return files

def _ffmpeg_os_info():
    plat = sys.platform
    if plat.startswith("darwin"):
        return {"os": "mac", "cmd": "brew install ffmpeg",
                "cmd_alt": "Скачай установщик с ffmpeg.org и перетащи ffmpeg в /usr/local/bin/"}
    if plat.startswith("win"):
        return {"os": "win", "cmd": "winget install Gyan.FFmpeg",
                "cmd_alt": "Скачай сборку с gyan.dev/ffmpeg/builds/, распакуй в C:\\ffmpeg"}
    return {"os": "linux", "cmd": "sudo apt install ffmpeg",
            "cmd_alt": "Для Fedora: sudo dnf install ffmpeg ; для Arch: sudo pacman -S ffmpeg"}

# ---------------------------------------------------------------------------
# Video purge
# ---------------------------------------------------------------------------
def _purge_videos(db, video_ids: list) -> int:
    if not video_ids:
        return 0
    videos = db.query(Video).filter(Video.id.in_(video_ids)).all()
    video_files = []
    all_img_ids = []
    all_img_paths = []
    for v in videos:
        video_files.append(v.path)
        imgs = db.query(ImageModel.id, ImageModel.path).filter(
            ImageModel.video_id == v.id
        ).all()
        for iid, ipath in imgs:
            all_img_ids.append(iid)
            all_img_paths.append(ipath)
    if all_img_ids:
        db.query(Annotation).filter(Annotation.image_id.in_(all_img_ids)).delete(synchronize_session=False)
        db.query(ImageTag).filter(ImageTag.image_id.in_(all_img_ids)).delete(synchronize_session=False)
        db.query(ImageModel).filter(ImageModel.id.in_(all_img_ids)).delete(synchronize_session=False)
    db.query(Video).filter(Video.id.in_(video_ids)).delete(synchronize_session=False)
    db.commit()
    for p in all_img_paths:
        _remove_file_safe(p)
    for iid in all_img_ids:
        _remove_thumb(iid)
    for vp in video_files:
        _remove_file_safe(vp)
    return len(videos)

# ---------------------------------------------------------------------------
# Корзина
# ---------------------------------------------------------------------------
def _purge_projects(db, project_ids: list) -> int:
    if not project_ids:
        return 0
    video_rows = db.query(Video.path).filter(Video.project_id.in_(project_ids)).all()
    video_paths = [r.path for r in video_rows]

    imgs = db.query(ImageModel.id, ImageModel.path).filter(
        ImageModel.project_id.in_(project_ids)
    ).all()
    img_ids = [im.id for im in imgs]
    img_paths = [im.path for im in imgs]
    tag_ids = [t.id for t in db.query(Tag.id).filter(Tag.project_id.in_(project_ids)).all()]

    if img_ids:
        db.query(Annotation).filter(Annotation.image_id.in_(img_ids)).delete(synchronize_session=False)
        db.query(ImageTag).filter(ImageTag.image_id.in_(img_ids)).delete(synchronize_session=False)
    if tag_ids:
        db.query(ImageTag).filter(ImageTag.tag_id.in_(tag_ids)).delete(synchronize_session=False)

    db.query(ImageModel).filter(ImageModel.project_id.in_(project_ids)).delete(synchronize_session=False)
    db.query(Video).filter(Video.project_id.in_(project_ids)).delete(synchronize_session=False)
    db.query(Tag).filter(Tag.project_id.in_(project_ids)).delete(synchronize_session=False)
    db.query(Project).filter(Project.id.in_(project_ids)).delete(synchronize_session=False)
    db.commit()

    for p in img_paths:
        _remove_file_safe(p)
    for iid in img_ids:
        _remove_thumb(iid)
    for vp in video_paths:
        _remove_file_safe(vp)

    log_status("warning", "trash", f"Полностью удалено проектов: {len(project_ids)}, "
                                   f"файлов: {len(img_paths)}")
    return len(project_ids)

def cleanup_expired_trash(db) -> int:
    default_ttl = get_trash_ttl_days(db)
    now = utcnow()
    total = 0

    proj_rows = (db.query(Project.id, Project.trash_ttl_days_override)
                   .filter(Project.is_deleted.is_(True))
                   .all())
    ttl_by_project = {}
    for pid, override in proj_rows:
        ttl = int(override) if override is not None else default_ttl
        ttl_by_project[pid] = ttl

    projects_by_ttl = defaultdict(list)
    for pid, ttl in ttl_by_project.items():
        if ttl <= 0:
            continue
        projects_by_ttl[ttl].append(pid)

    for ttl, pids in projects_by_ttl.items():
        cutoff = now - timedelta(days=ttl)
        while True:
            chunk = (db.query(Project.id)
                       .filter(Project.id.in_(pids),
                               Project.deleted_at.isnot(None),
                               Project.deleted_at < cutoff)
                       .limit(50).all())
            if not chunk:
                break
            ids = [r.id for r in chunk]
            _purge_projects(db, ids)
            total += len(ids)
            if len(chunk) < 50:
                break

    vid_rows = (db.query(Video.id, Video.project_id, Video.deleted_at)
                  .filter(Video.is_deleted.is_(True)).all())
    vid_to_purge = []
    for vid, pid, deleted_at in vid_rows:
        ttl = ttl_by_project.get(pid, default_ttl)
        if ttl <= 0:
            continue
        if not deleted_at:
            continue
        if deleted_at < now - timedelta(days=ttl):
            vid_to_purge.append(vid)
    if vid_to_purge:
        total += _purge_videos(db, vid_to_purge)

    CHUNK = 500
    img_rows = (db.query(ImageModel.id, ImageModel.project_id)
                  .filter(ImageModel.is_deleted.is_(True))
                  .all())
    imgs_by_ttl = defaultdict(list)
    for iid, pid in img_rows:
        ttl = ttl_by_project.get(pid, default_ttl)
        if ttl <= 0:
            continue
        imgs_by_ttl[ttl].append(iid)

    for ttl, iids in imgs_by_ttl.items():
        cutoff = now - timedelta(days=ttl)
        while True:
            candidates = (db.query(ImageModel.id, ImageModel.path)
                            .filter(ImageModel.id.in_(iids),
                                    ImageModel.deleted_at.isnot(None),
                                    ImageModel.deleted_at < cutoff)
                            .limit(CHUNK).all())
            if not candidates:
                break
            cids = [r.id for r in candidates]
            cpaths = [r.path for r in candidates]
            db.query(Annotation).filter(Annotation.image_id.in_(cids)).delete(synchronize_session=False)
            db.query(ImageTag).filter(ImageTag.image_id.in_(cids)).delete(synchronize_session=False)
            db.query(ImageModel).filter(ImageModel.id.in_(cids)).delete(synchronize_session=False)
            db.commit()
            for p in cpaths:
                _remove_file_safe(p)
            for iid in cids:
                _remove_thumb(iid)
            total += len(candidates)
            if len(candidates) < CHUNK:
                break

    return total

def _start_trash_cleaner_thread():
    def loop():
        while True:
            try:
                db = SessionLocal()
                try:
                    n = cleanup_expired_trash(db)
                    if n:
                        log.info("Корзина: удалено устаревших объектов %d", n)
                finally:
                    db.close()
            except Exception:
                log.exception("trash cleaner error")
            threading.Event().wait(6 * 3600)
    t = threading.Thread(target=loop, daemon=True, name="trash-cleaner")
    t.start()

# ---------------------------------------------------------------------------
# Скачивание моделей
# ---------------------------------------------------------------------------
BOOTSTRAP_STATE = {
    "status": "idle", "message": "", "progress": 0.0, "filename": "",
    "started_at": None, "finished_at": None,
}
BOOTSTRAP_LOCK = threading.Lock()
BOOTSTRAP_EVENT = threading.Event()
BOOTSTRAP_THREAD = None
_MODEL_ACTIVATION_LOCK = threading.Lock()

def _bootstrap_snapshot():
    with BOOTSTRAP_LOCK:
        return dict(BOOTSTRAP_STATE)

def _bootstrap_set(**kwargs):
    with BOOTSTRAP_LOCK:
        BOOTSTRAP_STATE.update(kwargs)
    BOOTSTRAP_EVENT.set()

def _yolo_filename(size: str, pretrain: str) -> str:
    size = size if size in ("n", "s", "m", "l", "x") else "n"
    if pretrain == "oiv7":
        return f"yolov8{size}-oiv7.pt"
    return f"yolov8{size}.pt"

def _download_with_progress(url: str, dest: str, on_progress=None,
                             retries: int = 2, expected_min_mb: int = 1,
                             expected_max_mb: int = 1024) -> None:
    tmp = dest + ".part"
    last_exc = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 DatasetBuilder"
            })
            with urllib.request.urlopen(req, timeout=90) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                if total > 0:
                    min_b = expected_min_mb * 1024 * 1024
                    max_b = expected_max_mb * 1024 * 1024
                    if total < min_b:
                        raise IOError(f"Content-Length {total} < ожидаемого {min_b}")
                    if total > max_b:
                        raise IOError(f"Content-Length {total} > ожидаемого {max_b}")
                done = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(128 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if on_progress:
                            if total > 0:
                                on_progress(done / total * 100.0, done, total)
                            else:
                                on_progress(None, done, 0)
            if total > 0 and done < total:
                raise IOError(f"Не докачано: {done} из {total} байт")
            if done < 512 * 1024:
                raise IOError(f"Файл подозрительно мал: {done} байт")
            with open(tmp, "rb") as f:
                head = f.read(4)
            if head[:2] != b'PK':
                raise IOError("Файл не является PyTorch-моделью (.pt — zip)")
            os.replace(tmp, dest)
            return
        except Exception as e:
            last_exc = e
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            if attempt < retries:
                log.warning("download attempt %d failed: %s; retry", attempt + 1, e)
                time.sleep(1.5 * (attempt + 1))
    raise last_exc

def _clear_yolo_cache():
    with _YOLO_CACHE_LOCK:
        old = list(_YOLO_CACHE.values())
        _YOLO_CACHE.clear()
    for m in old:
        try:
            del m
        except Exception:
            pass
    try:
        gc.collect()
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass

def _download_model_worker(size: str, pretrain: str, custom_name: str, auto_activate: bool) -> None:
    global BOOTSTRAP_THREAD
    try:
        fname = _yolo_filename(size, pretrain)
        url = YOLO_URL_TEMPLATE.format(tag=YOLO_RELEASE_TAG, name=fname)
        if custom_name:
            target_name = _sanitize_model_name(custom_name) or fname
        else:
            target_name = fname
        target_name = _unique_model_name_from_disk(target_name)
        target_path = os.path.join(MODEL_DIR, target_name)

        log_status("info", "model", f"Скачивание модели: {fname}")
        _bootstrap_set(
            status="downloading", message=f"Скачиваем {fname} …",
            progress=0.0, filename=target_name,
            started_at=utcnow().isoformat(), finished_at=None,
        )

        def cb(pct, done, total):
            if pct is None:
                msg = f"Скачиваем {fname} … {done / (1024*1024):.1f} МБ"
                _bootstrap_set(message=msg, progress=0.0)
            else:
                msg = f"Скачиваем {fname} … {pct:.1f}%  ({done/(1024*1024):.1f} МБ)"
                _bootstrap_set(message=msg, progress=round(pct, 1))

        _download_with_progress(url, target_path, on_progress=cb)

        activate = auto_activate
        if not activate:
            existing_active = None
            try:
                db2 = SessionLocal()
                try:
                    existing_active = get_setting(db2, SETTING_ACTIVE_MODEL, "")
                finally:
                    db2.close()
            except Exception:
                log.exception("check active model failed")
            if not existing_active:
                activate = True

        if activate:
            try:
                with _MODEL_ACTIVATION_LOCK:
                    db2 = SessionLocal()
                    try:
                        set_setting(db2, SETTING_ACTIVE_MODEL, target_name)
                    finally:
                        db2.close()
                    _clear_yolo_cache()
                    _invalidate_model_classes_cache()
            except Exception:
                log.exception("activate %s failed", target_name)

        _bootstrap_set(
            status="done", message=f"Модель загружена: {target_name}",
            progress=100.0, filename=target_name,
            finished_at=utcnow().isoformat(),
        )
        log_status("success", "model", f"Модель загружена: {target_name}")
    except Exception as e:
        log.exception("download error")
        log_status("error", "model", f"Не удалось скачать модель: {e}")
        _bootstrap_set(
            status="error", message=f"Не удалось скачать модель: {e}",
            finished_at=utcnow().isoformat(),
        )
    finally:
        with BOOTSTRAP_LOCK:
            BOOTSTRAP_THREAD = None
        BOOTSTRAP_EVENT.set()

def _bootstrap_default_model_if_empty():
    try:
        existing = [f for f in os.listdir(MODEL_DIR) if f.endswith(".pt")]
        if existing:
            return
        log_status("info", "model", "Моделей нет. Скачиваю yolov8n-oiv7.pt")
        _download_model_worker("n", "oiv7", "pig.pt", auto_activate=True)
    except Exception:
        log.exception("bootstrap error")

# ---------------------------------------------------------------------------
# Letterbox / pHash / IoU
# ---------------------------------------------------------------------------
def letterbox(img: Image.Image, target_size=FIXED_SIZE, fill=LETTERBOX_FILL) -> Image.Image:
    tw, th = target_size
    w, h = img.size
    if w == 0 or h == 0:
        return Image.new("RGB", (tw, th), fill)
    scale = min(tw / w, th / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (tw, th), fill)
    canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    return canvas

_DCT_TABLE_CACHE = {}
_NP_DCT_CACHE = {}

def _dct_cos_table(n: int):
    t = _DCT_TABLE_CACHE.get(n)
    if t is None:
        t = [[math.cos((2 * x + 1) * u * math.pi / (2 * n)) for x in range(n)]
             for u in range(n)]
        _DCT_TABLE_CACHE[n] = t
    return t

def _dct_matrix_np(N: int, hash_size: int):
    key = (N, hash_size)
    if key in _NP_DCT_CACHE:
        return _NP_DCT_CACHE[key]
    C = _np.zeros((hash_size, N), dtype=_np.float32)
    for u in range(hash_size):
        for x in range(N):
            C[u, x] = _np.cos((2 * x + 1) * u * _np.pi / (2 * N))
    _NP_DCT_CACHE[key] = C
    return C

def phash_hex(image_path, hash_size=8, highfreq_factor=4) -> str:
    N = hash_size * highfreq_factor
    try:
        img = Image.open(image_path).convert("L").resize((N, N), Image.Resampling.LANCZOS)
    except Exception:
        return ""
    if _HAS_NUMPY:
        try:
            arr = _np.asarray(img, dtype=_np.float32)
            C = _dct_matrix_np(N, hash_size)
            dct = C @ arr @ C.T
            flat = dct.flatten()
            vals = flat[1:]
            med = _np.median(vals)
            value = 0
            for b in (flat > med):
                value = (value << 1) | int(b)
            return format(value, "016x")
        except Exception:
            log.exception("phash numpy path failed, falling back to python")
    pixels = list(img.getdata())
    cos_t = _dct_cos_table(N)
    row_dct = [[0.0] * N for _ in range(hash_size)]
    for u in range(hash_size):
        cu = cos_t[u]
        for y in range(N):
            s = 0.0
            base = y * N
            for x in range(N):
                s += pixels[base + x] * cu[x]
            row_dct[u][y] = s
    dct = [[0.0] * hash_size for _ in range(hash_size)]
    for u in range(hash_size):
        for v in range(hash_size):
            cv = cos_t[v]
            s = 0.0
            for y in range(N):
                s += row_dct[u][y] * cv[y]
            dct[u][v] = s
    vals = []
    for u in range(hash_size):
        for v in range(hash_size):
            if u == 0 and v == 0:
                continue
            vals.append(dct[u][v])
    vals.sort()
    med = vals[len(vals) // 2]
    bits = 0
    for u in range(hash_size):
        for v in range(hash_size):
            bits = (bits << 1) | (1 if dct[u][v] > med else 0)
    return format(bits, "016x")

def hamming_hex(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 64
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 64


def _hex_to_int(h, expected_len: Optional[int] = 16) -> int:
    """Быстрый парсер pHash в int. Возвращает -1 для невалидных.

    V7.9.3: expected_len=None — длина не проверяется (для будущих схем
    хеширования с другим числом бит).
    """
    if not isinstance(h, str) or not h:
        return -1
    if expected_len is not None and len(h) != expected_len:
        return -1
    try:
        return int(h, 16)
    except (TypeError, ValueError):
        return -1


def _hamming_int(a: int, b: int) -> int:
    """Хэмминг между двумя int-представлениями pHash. -1 = 64 (совместимо с hamming_hex)."""
    if a < 0 or b < 0:
        return 64
    return bin(a ^ b).count("1")


def find_duplicate(db, project_id: int, phash: str):
    if not phash or len(phash) < 4:
        return None
    bucket = phash[:4]
    target_int = _hex_to_int(phash)
    # V8.1.0: LIMIT — не тянем весь бакет, дубликат всё равно найдём первым.
    rows = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False),
                      ImageModel.phash.isnot(None),
                      ImageModel.phash.like(f"{bucket}%"))
              .limit(200)
              .all())
    for r in rows:
        if _hamming_int(target_int, _hex_to_int(r.phash)) <= PHASH_DUPLICATE_THRESHOLD:
            return r
    if len(rows) < 4:
        rest = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
                  .filter(ImageModel.project_id == project_id,
                          ImageModel.is_deleted.is_(False),
                          ImageModel.phash.isnot(None),
                          ~ImageModel.phash.like(f"{bucket}%"))
                  .limit(500).all())
        for r in rest:
            if _hamming_int(target_int, _hex_to_int(r.phash)) <= PHASH_DUPLICATE_THRESHOLD:
                return r
    return None

def _iou_xywh(a, b):
    ax1, ay1 = a["x"], a["y"]
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx1, by1 = b["x"], b["y"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / ua if ua > 0 else 0.0

def dedup_boxes(anns, iou_thr=DEDUP_IOU_THRESHOLD):
    if not anns:
        return anns
    srt = sorted(anns, key=lambda a: (a.get("confidence") or 0.0), reverse=True)
    keep = []
    for a in srt:
        if all(_iou_xywh(a, k) < iou_thr for k in keep):
            keep.append(a)
    return keep

# ---------------------------------------------------------------------------
# Thumbnails
# ---------------------------------------------------------------------------
def _thumb_path(image_id: int) -> str:
    if not isinstance(image_id, int) or image_id <= 0:
        raise ValueError(f"invalid image_id: {image_id!r}")
    return os.path.join(THUMB_DIR, f"{image_id}.jpg")

def _remove_thumb(image_id: int):
    try:
        _remove_file_safe(_thumb_path(image_id))
    except ValueError:
        pass

def ensure_thumb(image_id: int, src_path: str) -> str:
    try:
        p = _thumb_path(image_id)
    except ValueError:
        log.warning("ensure_thumb: invalid image_id %r", image_id)
        return ""
    if os.path.exists(p):
        return p
    if not src_path or not os.path.exists(src_path):
        log.warning("ensure_thumb: source not found: %s", src_path)
        return ""
    try:
        img = Image.open(src_path).convert("RGB")
        img.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", THUMB_SIZE, (235, 235, 240))
        ox = (THUMB_SIZE[0] - img.width) // 2
        oy = (THUMB_SIZE[1] - img.height) // 2
        canvas.paste(img, (ox, oy))
        canvas.save(p, "JPEG", quality=82)
    except Exception as e:
        log.warning("thumb fail for %s: %s", image_id, e)
        return ""
    return p


# V8.1.0: пул для фоновой генерации миниатюр.
_THUMB_POOL = None
_THUMB_POOL_LOCK = threading.Lock()


def _get_thumb_pool():
    global _THUMB_POOL
    if _THUMB_POOL is not None:
        return _THUMB_POOL
    with _THUMB_POOL_LOCK:
        if _THUMB_POOL is None:
            _THUMB_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumb-gen")
    return _THUMB_POOL


def _queue_thumb(image_id: int, src_path: str):
    """V8.1.0: не блокируем HTTP-запрос генерацией миниатюры.

    При ошибке submit — fallback на синхронный вызов, чтобы точно не потерять thumb.
    """
    try:
        _get_thumb_pool().submit(ensure_thumb, image_id, src_path)
    except Exception:
        log.exception("queue_thumb failed, falling back to sync")
        try:
            ensure_thumb(image_id, src_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Имена файлов
# ---------------------------------------------------------------------------
def _split_name_ext(name: str):
    m = re.match(r'^(.*?)(\.[^.]*)?$', name)
    base = m.group(1) if m and m.group(1) else name
    ext = m.group(2) if m and m.group(2) else ''
    return base, ext

def sanitize_display_name(name: str, fallback: str = "image") -> str:
    if not name:
        return fallback
    base, ext = _split_name_ext(name)
    base = INVALID_CHARS_RE.sub('_', base).strip().rstrip('.')
    ext = INVALID_CHARS_RE.sub('', ext).strip()
    if not base:
        base = fallback
    return base + ext

def validate_user_filename(name: str):
    if not name:
        raise HTTPException(400, "Имя не может быть пустым")
    if len(name) > 200:
        raise HTTPException(400, {"key": "error.nameTooLong", "fallback": "Слишком длинное имя"})
    if INVALID_CHARS_RE.search(name):
        raise HTTPException(400, 'Недопустимые символы: \\ / : * ? " < > |')
    if name in ('.', '..'):
        raise HTTPException(400, "Недопустимое имя")
    if name != name.strip():
        raise HTTPException(400, "Имя не может начинаться или заканчиваться пробелом")
    if name.endswith('.'):
        raise HTTPException(400, "Имя не может заканчиваться точкой")

def make_unique_filename(db, project_id: int, filename: str, exclude_id: int = None) -> str:
    q = db.query(ImageModel.filename).filter(
        ImageModel.project_id == project_id,
        ImageModel.is_deleted.is_(False),
    )
    if exclude_id is not None:
        q = q.filter(ImageModel.id != exclude_id)
    existing = {r[0] for r in q.all()}
    if filename not in existing:
        return filename
    base, ext = _split_name_ext(filename)
    m = re.match(r'^(.*) \((\d+)\)$', base)
    base_root = m.group(1) if m else base
    max_n = 0
    pattern = re.compile(r'^' + re.escape(base_root) + r' \((\d+)\)$')
    for ex in existing:
        e_base, e_ext = _split_name_ext(ex)
        if e_ext.lower() != ext.lower():
            continue
        m2 = pattern.match(e_base)
        if m2:
            n = int(m2.group(1))
            if n > max_n:
                max_n = n
    return f"{base_root} ({max_n + 1}){ext}"

def _unique_name_mem(name: str, used: set) -> str:
    if name not in used:
        used.add(name)
        return name
    base, ext = _split_name_ext(name)
    m = re.match(r'^(.*) \((\d+)\)$', base)
    base_root = m.group(1) if m else base
    n = 1
    while f"{base_root} ({n}){ext}" in used:
        n += 1
    result = f"{base_root} ({n}){ext}"
    used.add(result)
    return result

def _is_image_ext(name: str) -> bool:
    _, ext = _split_name_ext(name)
    return ext.lower() in IMAGE_EXTS

# ---------------------------------------------------------------------------
# Определение формата картинок
# ---------------------------------------------------------------------------
_MAGIC_JPEG = b'\xff\xd8\xff'
_MAGIC_PNG = b'\x89PNG\r\n\x1a\n'
_MAGIC_GIF87 = b'GIF87a'
_MAGIC_GIF89 = b'GIF89a'
_MAGIC_BMP = b'BM'
_MAGIC_TIFF_LE = b'II*\x00'
_MAGIC_TIFF_BE = b'MM\x00*'

def _detect_image_format(data: bytes) -> Optional[str]:
    if len(data) < 16:
        return None
    if data.startswith(_MAGIC_JPEG):
        return "JPEG"
    if data.startswith(_MAGIC_PNG):
        return "PNG"
    if data.startswith(_MAGIC_GIF87) or data.startswith(_MAGIC_GIF89):
        return "GIF"
    if data.startswith(_MAGIC_BMP):
        return "BMP"
    if data.startswith(_MAGIC_TIFF_LE) or data.startswith(_MAGIC_TIFF_BE):
        return "TIFF"
    if data[0:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "WEBP"
    if data[4:8] == b'ftyp':
        brand = data[8:12]
        if brand in (b'avif', b'avis'):
            return "AVIF"
        if brand in (b'heic', b'heix', b'hevc', b'hevx', b'mif1', b'msf1'):
            return "HEIF"
    return None

def _open_image_safe(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except Image.DecompressionBombError:
        raise HTTPException(413, "Изображение слишком большое")
    except Image.DecompressionBombWarning:
        raise HTTPException(413, "Изображение слишком большое")
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e).lower()
        if "avif" in msg or "heif" in msg or "heic" in msg or "decoder" in msg:
            raise HTTPException(
                415,
                "Формат требует плагина Pillow. Установи: "
                "pip install pillow-avif-plugin pillow-heif"
            )
        raise HTTPException(400, "Invalid image")

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
class SimpleRateLimiter:
    def __init__(self, max_requests: int, window_sec: float):
        self.max_requests = max_requests
        self.window = window_sec
        self._buckets: dict = defaultdict(list)
        self._lock = threading.Lock()
    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets[key]
            cutoff = now - self.window
            bucket[:] = [t for t in bucket if t > cutoff]
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True

_limiter_autolabel = SimpleRateLimiter(max_requests=60, window_sec=60)
_limiter_train = SimpleRateLimiter(max_requests=5, window_sec=300)
_limiter_upload = SimpleRateLimiter(max_requests=300, window_sec=60)
_limiter_import = SimpleRateLimiter(max_requests=5, window_sec=600)

def _rate_limit(limiter: SimpleRateLimiter, key: str, msg: str):
    if not limiter.check(key):
        raise HTTPException(429, msg)

def _safe_error_message(e: Exception, context: str = "") -> str:
    name = type(e).__name__
    if "OperationalError" in name or "IntegrityError" in name or "ProgrammingError" in name:
        return f"{context}: ошибка БД" if context else "Ошибка БД"
    msg = str(e)
    msg = re.sub(r'/[^\s]+/', '/…/', msg)
    msg = msg[:200]
    return f"{context}: {msg}" if context else msg

# ---------------------------------------------------------------------------
# Авторазметка
# ---------------------------------------------------------------------------
_YOLO_CACHE = OrderedDict()
_YOLO_CACHE_LOCK = threading.Lock()

def _get_yolo_model(model_path: str):
    with _YOLO_CACHE_LOCK:
        m = _YOLO_CACHE.get(model_path)
        if m is not None:
            _YOLO_CACHE.move_to_end(model_path)
            return m
    from ultralytics import YOLO
    m = YOLO(model_path)
    with _YOLO_CACHE_LOCK:
        _YOLO_CACHE[model_path] = m
        # V7.9.0: LRU на 2 модели. Позволяет держать в памяти активную + предыдущую
        # без перезагрузки с диска (~1–2 с экономии при переключении туда-обратно).
        while len(_YOLO_CACHE) > 2:
            _YOLO_CACHE.popitem(last=False)
    return m

def _autolabel_image_predict(img_path: str, model, W: int, H: int,
                              target_class_ids: set,
                              target_label: str,
                              conf: float = None,
                              tta: bool = False):
    if conf is None:
        conf = CONF_THRESHOLD
    # V8.1.0: tta — test-time augmentation (медленнее ~2×, точнее)
    results = model(img_path, conf=conf, verbose=False, augment=bool(tta))
    raw = []
    for r in results:
        for box in r.boxes:
            try:
                cls_id = int(box.cls[0])
            except Exception:
                cls_id = 0
            if target_class_ids and cls_id not in target_class_ids:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            try:
                bconf = float(box.conf[0])
            except Exception:
                bconf = None
            raw.append({"x": x1 / W, "y": y1 / H,
                        "w": (x2 - x1) / W, "h": (y2 - y1) / H,
                        "label": target_label, "confidence": bconf})
    return dedup_boxes(raw)

def _save_autolabel(db, image_id: int, anns: list, label: str):
    _save_autolabel_no_commit(db, image_id, anns, label)
    db.commit()

def _save_autolabel_no_commit(db, image_id: int, anns: list, label: str):
    db.query(Annotation).filter(
        Annotation.image_id == image_id,
        Annotation.is_frozen.is_(False)
    ).delete(synchronize_session=False)
    if anns:
        db.bulk_save_objects([
            Annotation(image_id=image_id, x=a["x"], y=a["y"], w=a["w"], h=a["h"],
                       label=label, confidence=a["confidence"],
                       is_frozen=False)
            for a in anns
        ])

def _is_duplicate_box(a: dict, b: dict,
                      iou_thr: float = 0.5,
                      center_dist_thr: float = 0.05) -> bool:
    """V8.2.0: рамки — дубликаты, если IoU > 0.5 ИЛИ центры ближе 5%."""
    if _iou_xywh(a, b) > iou_thr:
        return True
    ax = a["x"] + a["w"] / 2
    ay = a["y"] + a["h"] / 2
    bx = b["x"] + b["w"] / 2
    by = b["y"] + b["h"] / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 < center_dist_thr


def _load_boxes_xywh(db, image_id: int) -> list:
    """V8.2.0: лёгкая выборка x/y/w/h (для проверки дубликатов)."""
    rows = (db.query(Annotation.x, Annotation.y,
                     Annotation.w, Annotation.h)
              .filter(Annotation.image_id == image_id).all())
    return [{"x": r.x, "y": r.y, "w": r.w, "h": r.h} for r in rows]


def _load_annotations(db, image_id: int) -> list:
    rows = (db.query(Annotation)
              .filter(Annotation.image_id == image_id)
              .order_by(Annotation.id).all())
    return [{"x": r.x, "y": r.y, "w": r.w, "h": r.h,
             "label": r.label, "confidence": r.confidence,
             "frozen": bool(r.is_frozen)} for r in rows]

def _autolabel_image_with_model(db, img, model, project, conf=None,
                                 tta=False, mode="add"):
    target_label = (project.object_class or DEFAULT_OBJECT_CLASS)
    target_ids = _resolve_target_class_ids(model, target_label)
    if not target_ids:
        raise HTTPException(
            422,
            f"Класс «{target_label}» не поддерживается активной моделью. "
            f"Выбери другую модель в настройках или обучи свою."
        )
    raw_new = _autolabel_image_predict(
        img.path, model, img.width, img.height, target_ids, target_label, conf, tta
    )

    # V8.2.0: два режима.
    if _norm_mode(mode) == "add":
        existing = _load_boxes_xywh(db, img.id)
        unique = []
        skipped = 0
        for d in raw_new:
            if any(_is_duplicate_box(d, e) for e in existing):
                skipped += 1
            else:
                unique.append(d)
        if unique:
            # V8.2.1: add_all вместо bulk_save_objects (SQLAlchemy 2.0).
            db.add_all([
                Annotation(image_id=img.id, x=a["x"], y=a["y"],
                           w=a["w"], h=a["h"], label=target_label,
                           confidence=a["confidence"], is_frozen=False)
                for a in unique
            ])
            db.commit()
        return {
            "boxes": _load_annotations(db, img.id),
            "added": len(unique),
            "skipped": skipped,
            "total": len(existing) + len(unique),
            "mode": "add",
        }
    # replace
    _save_autolabel(db, img.id, raw_new, target_label)
    return {
        "boxes": _load_annotations(db, img.id),
        "added": len(raw_new),
        "skipped": 0,
        "total": len(raw_new),
        "mode": "replace",
    }

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

def _read_stream_and_parse(proc, on_line, idle_timeout: float = 2.0):
    """Читаем stdout дочернего процесса в отдельном потоке — работает на всех ОС.

    Раньше использовался select.select(), который на Windows умеет работать
    только с сокетами, но не с пайпами. Из-за этого цикл молча выходил на
    первой итерации, и прогресс обучения (эпохи, лог) никогда не обновлялся.
    """
    def _reader():
        try:
            for raw in iter(proc.stdout.readline, b''):
                text = raw.decode('utf-8', errors='replace').rstrip('\r\n')
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
    return env

def _run_training_thread(args, run_dir, run_id, custom_name):
    global TRAIN_PROCESS
    try:
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
                                set_setting(db3, SETTING_ACTIVE_MODEL, partial_name)
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
                shutil.copy(best, os.path.join(MODEL_DIR, new_name))
                try:
                    with _MODEL_ACTIVATION_LOCK:
                        db2 = SessionLocal()
                        try:
                            set_setting(db2, SETTING_ACTIVE_MODEL, new_name)
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

def _batch_worker(image_ids, model_path, project_id, mode="add"):
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
            model = _get_yolo_model(model_path)
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
                   f"Батч-авторазметка: {total} изобр., класс «{target_label}», "
                   f"режим={_norm_mode(mode)}")
        BATCH_EVENT.set()
        pending_since_commit = 0
        for iid in image_ids:
            if BATCH_STOP.is_set():
                db.rollback()
                with BATCH_LOCK:
                    BATCH_STATE["status"] = "stopped"
                    BATCH_STATE["message"] = "Остановлено пользователем"
                log_status("warning", "autolabel", "Батч-авторазметка остановлена")
                BATCH_EVENT.set()
                return
            img = db.query(ImageModel).filter(ImageModel.id == iid).first()
            if not img:
                with BATCH_LOCK:
                    BATCH_STATE["done"] += 1
                    BATCH_STATE["failed"] += 1
                BATCH_EVENT.set()
                continue
            with BATCH_LOCK:
                BATCH_STATE["current_id"] = iid
                BATCH_STATE["current_filename"] = img.filename
            BATCH_EVENT.set()
            try:
                raw_new = _autolabel_image_predict(
                    img.path, model, img.width, img.height, target_ids, target_label
                )
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
                    pending_since_commit += 1 if unique else 0
                    with BATCH_LOCK:
                        BATCH_STATE["added"] += len(unique)
                        BATCH_STATE["skipped"] += skipped_n
                        BATCH_STATE["done"] += 1
                else:
                    _save_autolabel_no_commit(db, iid, raw_new, target_label)
                    pending_since_commit += 1
                    with BATCH_LOCK:
                        BATCH_STATE["added"] += len(raw_new)
                        BATCH_STATE["done"] += 1
            except Exception as e:
                log.warning("batch fail image %s: %s", iid, e)
                db.rollback()
                pending_since_commit = 0
                with BATCH_LOCK:
                    BATCH_STATE["done"] += 1
                    BATCH_STATE["failed"] += 1
            if pending_since_commit >= BATCH_AUTOLABEL_COMMIT_EVERY:
                db.commit()
                pending_since_commit = 0
            BATCH_EVENT.set()
        if pending_since_commit:
            db.commit()
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
    t = threading.Thread(target=_bootstrap_default_model_if_empty,
                         daemon=True, name="model-bootstrap")
    t.start()
    # V7.9.3: фоновые задачи — не блокируем старт приложения.
    threading.Thread(target=_backfill_v760, daemon=True,
                     name="backfill-v760").start()
    threading.Thread(target=_warm_yolo_cache, daemon=True,
                     name="yolo-warmup").start()
    log_status("info", "system", f"Dataset Builder {APP_VERSION} запущен")
    yield
    # V8.1.0: корректно завершаем пул миниатюр.
    try:
        if _THUMB_POOL is not None:
            _THUMB_POOL.shutdown(wait=True, cancel_futures=True)
    except Exception:
        log.exception("thumb pool shutdown failed")
    log_status("info", "system", "Приложение останавливается")

app = FastAPI(title=f"Dataset Builder {APP_VERSION}", lifespan=lifespan)

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:8]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response

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

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

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
@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    rows = (db.query(Project)
              .filter(Project.is_deleted.is_(False))
              .order_by(Project.id).all())
    counts = dict(
        db.query(ImageModel.project_id, func.count(ImageModel.id))
          .filter(ImageModel.is_deleted.is_(False))
          .group_by(ImageModel.project_id).all()
    )
    ann_counts = dict(
        db.query(ImageModel.project_id, func.count(Annotation.id))
          .join(Annotation, Annotation.image_id == ImageModel.id)
          .filter(ImageModel.is_deleted.is_(False))
          .group_by(ImageModel.project_id).all()
    )
    return [{
        "id": p.id, "name": p.name,
        "images_count": int(counts.get(p.id, 0)),
        "annotations_count": int(ann_counts.get(p.id, 0)),
        "object_class": p.object_class or DEFAULT_OBJECT_CLASS,
        "object_class_source": p.object_class_source or "list",
        "trash_ttl_days_override": p.trash_ttl_days_override,
        "thumbnail_size": p.thumbnail_size,
        "default_zoom": p.default_zoom,
    } for p in rows]

@app.post("/api/projects")
def create_project(
    name: str = Form(...),
    object_class: str = Form(DEFAULT_OBJECT_CLASS),
    object_class_source: str = Form("list"),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name:
        raise HTTPException(400, {"key": "error.emptyProjectName", "fallback": "Пустое имя проекта"})
    if len(name) > 255:
        raise HTTPException(400, "Слишком длинное имя")
    cls = _validate_object_class(object_class)
    src = _validate_object_class_source(object_class_source)
    p = Project(name=name, created_at=utcnow(), is_deleted=False,
                object_class=cls, object_class_source=src)
    db.add(p)
    db.commit()
    db.refresh(p)
    log_status("success", "project",
               f"Создан проект «{name}» (id={p.id}, класс={cls})")
    return {
        "id": p.id, "name": p.name,
        "images_count": 0, "annotations_count": 0,
        "object_class": p.object_class,
        "object_class_source": p.object_class_source,
    }

@app.delete("/api/projects/{project_id}")
def soft_delete_project(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    if proj.is_deleted:
        return {"status": "ok", "deleted_id": project_id, "soft": True, "already_deleted": True}
    proj.is_deleted = True
    proj.deleted_at = utcnow()
    db.commit()
    log_status("warning", "project", f"Проект «{proj.name}» перемещён в корзину")
    return {"status": "ok", "deleted_id": project_id, "soft": True, "name": proj.name}

@app.post("/api/projects/{project_id}/restore")
def restore_project(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    if not proj.is_deleted:
        return {"status": "ok", "restored_id": project_id, "name": proj.name, "already_active": True}
    proj.is_deleted = False
    proj.deleted_at = None
    db.commit()
    log_status("info", "project", f"Проект «{proj.name}» восстановлен из корзины")
    return {"status": "ok", "restored_id": project_id, "name": proj.name}

@app.delete("/api/projects/{project_id}/permanent")
def permanent_delete_project(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    name = proj.name
    _purge_projects(db, [project_id])
    log_status("warning", "project", f"Проект «{name}» удалён навсегда")
    return {"status": "ok", "deleted_id": project_id, "permanent": True}

@app.get("/api/projects/{project_id}/info")
def project_info(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    images_count = (db.query(func.count(ImageModel.id))
                      .filter(ImageModel.project_id == project_id,
                              ImageModel.is_deleted.is_(False))
                      .scalar() or 0)
    ann_count = (db.query(func.count(Annotation.id))
                   .join(ImageModel, Annotation.image_id == ImageModel.id)
                   .filter(ImageModel.project_id == project_id,
                           ImageModel.is_deleted.is_(False))
                   .scalar() or 0)
    return {
        "id": proj.id, "name": proj.name,
        "object_class": proj.object_class or DEFAULT_OBJECT_CLASS,
        "object_class_source": proj.object_class_source or "list",
        "images_count": int(images_count),
        "annotations_count": int(ann_count),
        "is_deleted": bool(proj.is_deleted),
        "trash_ttl_days_override": proj.trash_ttl_days_override,
        "thumbnail_size": proj.thumbnail_size,
        "default_zoom": proj.default_zoom,
        "global_trash_ttl": get_trash_ttl_days(db),
    }

@app.patch("/api/projects/{project_id}/settings")
def update_project_settings(
    project_id: int,
    payload: ProjectSettingsIn,
    db: Session = Depends(get_db),
):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    changed = []

    if payload.object_class is not None:
        new_class = _validate_object_class(payload.object_class)
        new_src = _validate_object_class_source(
            payload.object_class_source if payload.object_class_source is not None
            else (proj.object_class_source or "list")
        )
        cls_changed = (proj.object_class or DEFAULT_OBJECT_CLASS) != new_class \
            or (proj.object_class_source or "list") != new_src
        if cls_changed:
            ann_count = (db.query(func.count(Annotation.id))
                           .join(ImageModel, Annotation.image_id == ImageModel.id)
                           .filter(ImageModel.project_id == project_id,
                                   ImageModel.is_deleted.is_(False))
                           .scalar() or 0)
            if ann_count > 0:
                raise HTTPException(
                    409,
                    f"В проекте уже размечено {ann_count} рамок. "
                    f"Сначала очистите разметку, потом меняйте класс."
                )
            proj.object_class = new_class
            proj.object_class_source = new_src
            changed.append(f"класс={new_class}")

    if payload.clear_ttl_override:
        if proj.trash_ttl_days_override is not None:
            proj.trash_ttl_days_override = None
            changed.append("ttl=global")
    elif payload.trash_ttl_days_override is not None:
        v = int(payload.trash_ttl_days_override)
        v = max(0, min(3650, v))
        if proj.trash_ttl_days_override != v:
            proj.trash_ttl_days_override = v
            changed.append(f"ttl={v}")

    if payload.clear_thumbnail_size:
        if proj.thumbnail_size is not None:
            proj.thumbnail_size = None
            changed.append("thumb=default")
    elif payload.thumbnail_size is not None:
        v = int(payload.thumbnail_size)
        if v not in VALID_THUMB_SIZES:
            raise HTTPException(400, f"thumbnail_size должен быть одним из: {VALID_THUMB_SIZES}")
        if proj.thumbnail_size != v:
            proj.thumbnail_size = v
            changed.append(f"thumb={v}")

    if payload.clear_default_zoom:
        if proj.default_zoom is not None:
            proj.default_zoom = None
            changed.append("zoom=default")
    elif payload.default_zoom is not None:
        v = float(payload.default_zoom)
        if v not in VALID_DEFAULT_ZOOMS:
            raise HTTPException(400, f"default_zoom должен быть одним из: {VALID_DEFAULT_ZOOMS}")
        if proj.default_zoom != v:
            proj.default_zoom = v
            changed.append(f"zoom={v}")

    if not changed:
        return {"status": "noop"}
    db.commit()
    log_status("info", "project",
               f"Проект «{proj.name}»: изменения — {', '.join(changed)}")
    return {
        "id": proj.id,
        "object_class": proj.object_class,
        "object_class_source": proj.object_class_source,
        "trash_ttl_days_override": proj.trash_ttl_days_override,
        "thumbnail_size": proj.thumbnail_size,
        "default_zoom": proj.default_zoom,
    }

@app.post("/api/projects/{project_id}/clear_annotations")
def clear_project_annotations(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    img_ids_q = (db.query(ImageModel.id)
                   .filter(ImageModel.project_id == project_id,
                           ImageModel.is_deleted.is_(False)))
    img_ids = [iid for (iid,) in img_ids_q.all()]
    if not img_ids:
        return {"status": "ok", "cleared": 0}
    total = (db.query(func.count(Annotation.id))
               .filter(Annotation.image_id.in_(img_ids))
               .scalar() or 0)
    db.query(Annotation).filter(Annotation.image_id.in_(img_ids)) \
        .delete(synchronize_session=False)
    db.commit()
    _invalidate_stats_cache(project_id)
    log_status("warning", "project",
               f"Проект «{proj.name}»: очищено рамок {total}")
    return {"status": "ok", "cleared": int(total)}

@app.get("/api/projects/trash")
def list_projects_trash(db: Session = Depends(get_db)):
    rows = (db.query(Project)
              .filter(Project.is_deleted.is_(True))
              .order_by(Project.deleted_at.desc(), Project.id.desc()).all())
    ttl = get_trash_ttl_days(db)
    now = utcnow()
    out = []
    for r in rows:
        cnt = db.query(func.count(ImageModel.id)).filter(
            ImageModel.project_id == r.id).scalar() or 0
        days_left = None
        eff_ttl = r.trash_ttl_days_override if r.trash_ttl_days_override is not None else ttl
        if r.deleted_at and eff_ttl > 0:
            days_left = max(0, (r.deleted_at + timedelta(days=eff_ttl) - now).days)
        out.append({
            "id": r.id, "name": r.name, "images_count": int(cnt),
            "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
            "days_left": days_left,
        })
    return out

@app.post("/api/projects/trash/empty")
def empty_projects_trash(db: Session = Depends(get_db)):
    ids = [r.id for r in db.query(Project.id).filter(Project.is_deleted.is_(True)).all()]
    if not ids:
        return {"status": "ok", "deleted": 0}
    _purge_projects(db, ids)
    return {"status": "ok", "deleted": len(ids)}

# ---------------------------------------------------------------------------
# Object classes
# ---------------------------------------------------------------------------
@app.get("/api/object_classes")
def object_classes(db: Session = Depends(get_db)):
    model_path = get_active_model_path(db)
    if not model_path:
        return {"source": "empty", "classes": [], "active_model": None}
    try:
        model = _get_yolo_model(model_path)
    except ImportError:
        return {"source": "empty", "classes": [], "active_model": None,
                "error": "ultralytics не установлен"}
    except Exception as e:
        log.exception("object_classes: cannot load model")
        return {"source": "empty", "classes": [], "active_model": None,
                "error": _safe_error_message(e)}
    names = _read_model_class_names(model)
    return {
        "source": "model" if names else "empty",
        "classes": names,
        "active_model": os.path.basename(model_path),
    }

# ---------------------------------------------------------------------------
# Логи
# ---------------------------------------------------------------------------
@app.get("/api/logs")
def get_logs(limit: int = 300, level: Optional[str] = None,
             category: Optional[str] = None):
    with STATUS_LOG_LOCK:
        items = list(STATUS_LOG)
    if level:
        items = [x for x in items if x.get("level") == level]
    if category:
        items = [x for x in items if x.get("category") == category]
    limit = max(1, min(2000, int(limit)))
    return {"items": items[-limit:], "total": len(items)}

@app.delete("/api/logs")
def clear_logs():
    with STATUS_LOG_LOCK:
        STATUS_LOG.clear()
    log_status("info", "system", "История статусов очищена")
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------
@app.get("/api/settings/trash_ttl")
def get_trash_ttl(db: Session = Depends(get_db)):
    return {"days": get_trash_ttl_days(db)}

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
        for f in sorted(os.listdir(MODEL_DIR)):
            if not f.endswith(".pt"):
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
    return {"models": result, "active": active}

@app.get("/api/models/compatibility")
def models_compatibility(object_class: str, db: Session = Depends(get_db)):
    obj = (object_class or "").strip().lower()
    if not obj:
        raise HTTPException(400, "object_class обязателен")
    names = []
    if os.path.isdir(MODEL_DIR):
        names = sorted([f for f in os.listdir(MODEL_DIR) if f.endswith(".pt")])
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
def activate_model(name: str = Form(...), db: Session = Depends(get_db)):
    with _MODEL_ACTIVATION_LOCK:
        p = _safe_model_path(name)
        if not os.path.exists(p):
            raise HTTPException(404, {"key": "error.modelNotFound", "fallback": "Модель не найдена"})
        set_setting(db, SETTING_ACTIVE_MODEL, name)
        _clear_yolo_cache()
        _invalidate_model_classes_cache()
    log_status("info", "model", f"Активная модель: {name}")
    return {"active": name}

@app.delete("/api/models/{name}")
def delete_model(name: str, db: Session = Depends(get_db)):
    p = _safe_model_path(name)
    if not os.path.exists(p):
        raise HTTPException(404, {"key": "error.modelNotFound", "fallback": "Модель не найдена"})
    if os.path.islink(p):
        raise HTTPException(400, "Символические ссылки не удаляются")
    active = get_setting(db, SETTING_ACTIVE_MODEL, "")
    if active == name:
        raise HTTPException(400, {"key": "error.modelActive", "fallback": "Это активная модель. Сначала переключись на другую."})
    pt_files = [f for f in os.listdir(MODEL_DIR) if f.endswith(".pt")]
    if len(pt_files) <= 1:
        raise HTTPException(400, {"key": "error.lastModel", "fallback": "Это последняя модель в папке."})
    try:
        os.remove(p)
    except OSError as e:
        raise HTTPException(500, f"Не удалось удалить: {e}")
    with _YOLO_CACHE_LOCK:
        _YOLO_CACHE.pop(p, None)
    _invalidate_model_classes_cache(name)
    log_status("warning", "model", f"Модель удалена: {name}")
    return {"status": "ok"}

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
            raise HTTPException(400, "Некорректный путь")
        try:
            os.rename(old_path, new_path)
        except OSError as e:
            raise HTTPException(500, f"Не удалось переименовать: {e}")
    if get_setting(db, SETTING_ACTIVE_MODEL, "") == name:
        set_setting(db, SETTING_ACTIVE_MODEL, clean)
    with _YOLO_CACHE_LOCK:
        _YOLO_CACHE.pop(old_path, None)
        _YOLO_CACHE.pop(new_path, None)
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
                         args=(size, pretrain, custom_name, True),
                         daemon=True, name="model-downloader")
    with BOOTSTRAP_LOCK:
        BOOTSTRAP_THREAD = t
    t.start()
    return {"status": "started", "size": size, "pretrain": pretrain}

# ---------------------------------------------------------------------------
# SAM
# ---------------------------------------------------------------------------
@app.get("/api/sam/status")
def sam_status(db: Session = Depends(get_db)):
    name = get_sam_model_name(db)
    with _SAM_CACHE_LOCK:
        loaded = name in _SAM_CACHE
    return {"model": name, "loaded": loaded, "available_models": list(VALID_SAM_MODELS)}

@app.post("/api/sam/set_model")
def sam_set_model(name: str = Form(...), db: Session = Depends(get_db)):
    if name not in VALID_SAM_MODELS:
        raise HTTPException(400, "Недопустимая SAM-модель")
    set_setting(db, SETTING_SAM_MODEL, name)
    _clear_sam_cache()
    log_status("info", "model", f"SAM-модель: {name}")
    return {"model": name}

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
        raise HTTPException(400, "Некорректный путь")
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
        raise HTTPException(400, "Некорректный путь")
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
        if base_model == "__active__":
            active = get_active_model_path(db)
            if not active:
                raise HTTPException(400, "Нет активной модели для дообучения")
            model_path = active
        else:
            size_map = {"n": "n", "s": "s", "m": "m", "l": "l", "x": "x"}
            size = size_map.get(base_model, "n")
            if pretrain_dataset == "oiv7":
                model_path = f"yolov8{size}-oiv7.pt"
            else:
                model_path = f"yolov8{size}.pt"
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join(RUNS_DIR, f"train_{run_id}")
        os.makedirs(run_dir, exist_ok=True)
        try:
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
                "run_id": run_id,
            })
        TRAIN_EVENT.set()
        log_status("info", "train",
                   f"Обучение запущено: project={project_id}, "
                   f"класс={proj.object_class}, "
                   f"base={os.path.basename(model_path)}, epochs={epochs}, "
                   f"name={custom_name or 'auto'}")
        freeze_layers = max(0, min(MAX_FREEZE_LAYERS, int(freeze)))
        lr0_val = max(1e-5, min(0.1, float(lr0)))
        yolo_cmd = shutil.which("yolo")
        if not yolo_cmd:
            exe_dir = os.path.dirname(sys.executable)
            for cand in ("yolo.exe", "yolo", "yolo.cmd"):
                p = os.path.join(exe_dir, cand)
                if os.path.exists(p):
                    yolo_cmd = p
                    break
        out_dir = os.path.join(run_dir, "output")
        if yolo_cmd:
            args = [yolo_cmd, "detect", "train", f"data={yaml_path}", f"model={model_path}",
                    f"epochs={epochs}", f"imgsz={imgsz}", f"project={out_dir}",
                    "name=train", "exist_ok=True", "device=cpu", "verbose=True",
                    f"freeze={freeze_layers}", f"lr0={lr0_val}", "patience=20",
                    "cos_lr=True", "warmup_epochs=3"]
        else:
            py_code = (
                "import sys, json; "
                "from ultralytics import YOLO; "
                "cfg = json.loads(sys.argv[1]); "
                "YOLO(cfg['model']).train(**cfg['kwargs'])"
            )
            cfg = {
                "model": model_path,
                "kwargs": {
                    "data": yaml_path, "epochs": epochs, "imgsz": imgsz,
                    "project": out_dir, "name": "train", "exist_ok": True,
                    "device": "cpu", "verbose": True, "freeze": freeze_layers,
                    "lr0": lr0_val, "patience": 20, "cos_lr": True, "warmup_epochs": 3,
                },
            }
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
def train_status():
    return _train_snapshot()

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
        raise HTTPException(404, "Video not found")
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
        raise HTTPException(404, "Video not found")
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
async def upload_video(
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
        frame_paths = _extract_frames(save_path, frames_dir, efps)
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
        raise HTTPException(500, "Не удалось извлечь ни одного кадра")
    if len(frame_paths) > MAX_VIDEO_FRAMES:
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
            pil = letterbox(pil, FIXED_SIZE, LETTERBOX_FILL)
            new_fname = f"{uuid.uuid4().hex}.jpg"
            new_path = os.path.join(UPLOAD_DIR, new_fname)
            pil.save(new_path, "JPEG", quality=95)
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
        im = ImageModel(
            project_id=project_id, filename=unique_name, path=new_path,
            width=FIXED_SIZE[0], height=FIXED_SIZE[1],
            is_deleted=False, phash=ph or None, is_hard=False,
            video_id=v.id, frame_index=idx,
            created_at=utcnow(), file_size=fsize,
        )
        db.add(im)
        db.flush()
        _queue_thumb(im.id, im.path)
        if first_image_id is None:
            first_image_id = im.id
        inserted += 1
        _remove_file_safe(fp)
        if inserted % 50 == 0:
            db.commit()
    v.images_count = inserted
    db.commit()
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
    db.query(Annotation).filter(Annotation.image_id == target_id).delete()
    for a in src_anns:
        db.add(Annotation(image_id=target_id, x=a.x, y=a.y, w=a.w, h=a.h,
                          label=a.label, confidence=None, is_frozen=False))
    db.commit()
    return {"status": "ok", "count": len(src_anns)}

# ---------------------------------------------------------------------------
# Теги
# ---------------------------------------------------------------------------
@app.get("/api/projects/{project_id}/tags")
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

@app.post("/api/projects/{project_id}/tags")
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

@app.patch("/api/tags/{tag_id}")
def update_tag(tag_id: int,
               name: Optional[str] = Form(None),
               color: Optional[str] = Form(None),
               db: Session = Depends(get_db)):
    t = db.query(Tag).filter(Tag.id == tag_id).first()
    if not t:
        raise HTTPException(404, "Tag not found")
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

@app.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    t = db.query(Tag).filter(Tag.id == tag_id).first()
    if not t:
        raise HTTPException(404, "Tag not found")
    db.query(ImageTag).filter(ImageTag.tag_id == tag_id).delete()
    db.delete(t)
    db.commit()
    log_status("warning", "tag", f"Удалён тег «{t.name}»")
    return {"status": "ok"}

@app.get("/api/images/{image_id}/tags")
def get_image_tags(image_id: int, db: Session = Depends(get_db)):
    rows = (db.query(Tag).join(ImageTag, ImageTag.tag_id == Tag.id)
              .filter(ImageTag.image_id == image_id).all())
    return [{"id": t.id, "name": t.name, "color": t.color or "#0071e3"} for t in rows]

@app.post("/api/images/{image_id}/tags")
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

@app.post("/api/images/batch_tags")
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

# ---------------------------------------------------------------------------
# Изображения
# ---------------------------------------------------------------------------
# V8.0.0: id-шники дубликатов с TTL-кэшем — для фильтра «Только дубликаты».
_DUPLICATES_CACHE: dict = {}
_DUPLICATES_CACHE_LOCK = threading.Lock()
_DUPLICATES_CACHE_TTL = 30.0


def _compute_duplicate_ids(project_id: int, db,
                            threshold: int = PHASH_DUPLICATE_THRESHOLD) -> set:
    """Все image_id, входящие хотя бы в одну группу дубликатов.

    Логика групп совпадает с project_duplicates, но без метаданных.
    """
    rows = (db.query(ImageModel.id, ImageModel.phash)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False),
                      ImageModel.phash.isnot(None))
              .all())
    if len(rows) < 2:
        return set()
    parent = {r.id: r.id for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # V8.1.0: 6-символьный префикс + лимит на бакет — избегаем O(n²)
    # при массовой загрузке близнецов с одинаковым pHash.
    BUCKET_PREFIX = 6
    BUCKET_LIMIT = 400
    buckets = defaultdict(list)
    for r in rows:
        if r.phash and len(r.phash) >= BUCKET_PREFIX:
            buckets[r.phash[:BUCKET_PREFIX]].append(r)
    keys = list(buckets.keys())
    for i, k in enumerate(keys):
        bucket = buckets[k]
        if len(bucket) > BUCKET_LIMIT:
            log.warning('dup check: bucket %s too big (%d), truncating',
                        k, len(bucket))
            bucket = bucket[:BUCKET_LIMIT]
        for ai in range(len(bucket)):
            r1 = bucket[ai]
            for bi in range(ai + 1, len(bucket)):
                r2 = bucket[bi]
                if hamming_hex(r1.phash, r2.phash) <= threshold:
                    union(r1.id, r2.id)
            for k2 in keys[i + 1:i + 6]:
                for r2 in buckets[k2][:BUCKET_LIMIT]:
                    if hamming_hex(r1.phash, r2.phash) <= threshold:
                        union(r1.id, r2.id)
    groups = defaultdict(list)
    for r in rows:
        groups[find(r.id)].append(r.id)
    out = set()
    for ids in groups.values():
        if len(ids) >= 2:
            out.update(ids)
    return out


def _get_duplicate_ids_cached(project_id: int, db) -> set:
    """TTL 30 секунд — не пересчитываем pHash на каждый запрос."""
    now = time.monotonic()
    with _DUPLICATES_CACHE_LOCK:
        cached = _DUPLICATES_CACHE.get(project_id)
        if cached and (now - cached[0]) < _DUPLICATES_CACHE_TTL:
            return cached[1]
    ids = _compute_duplicate_ids(project_id, db)
    with _DUPLICATES_CACHE_LOCK:
        _DUPLICATES_CACHE[project_id] = (now, ids)
    return ids


@app.post("/api/projects/{project_id}/images")
def upload_image(project_id: int, file: UploadFile = File(...),
                 db: Session = Depends(get_db)):
    _rate_limit(_limiter_upload, "local", {"key": "error.rateLimited", "fallback": "Слишком много запросов. Подожди минуту."})
    proj = db.query(Project).filter(Project.id == project_id,
                                     Project.is_deleted.is_(False)).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    content_length = file.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"Файл больше {MAX_UPLOAD_MB} МБ")
        except (ValueError, TypeError):
            pass
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Файл больше {MAX_UPLOAD_MB} МБ")
    fmt = _detect_image_format(data)
    if not fmt:
        log_status("warning", "upload", f"Не картинка (magic bytes): {file.filename}")
        raise HTTPException(400, "Unsupported image format")
    try:
        img = _open_image_safe(data).convert("RGB")
    except HTTPException:
        raise
    except Exception:
        log_status("warning", "upload", f"Некорректное изображение: {file.filename}")
        raise HTTPException(400, "Invalid image")
    img = letterbox(img, FIXED_SIZE, LETTERBOX_FILL)
    fname = f"{uuid.uuid4().hex}.jpg"
    path = os.path.join(UPLOAD_DIR, fname)
    img.save(path, "JPEG", quality=95)
    try:
        ph = phash_hex(path)
    except Exception:
        ph = ""
    dup = find_duplicate(db, project_id, ph)
    if dup:
        _remove_file_safe(path)
        log_status("info", "upload", f"Дубликат: {file.filename} похож на «{dup.filename}»")
        raise HTTPException(409, f"Дубликат: похоже на «{dup.filename}»")
    original_name = sanitize_display_name(file.filename or fname, fallback=fname)
    unique_name = make_unique_filename(db, project_id, original_name)
    try:
        fsize = os.path.getsize(path)
    except OSError:
        fsize = len(data)
    im = ImageModel(
        project_id=project_id, filename=unique_name, path=path,
        width=FIXED_SIZE[0], height=FIXED_SIZE[1],
        is_deleted=False, phash=ph or None, is_hard=False,
        created_at=utcnow(), file_size=fsize,
    )
    db.add(im)
    db.commit()
    db.refresh(im)
    _queue_thumb(im.id, im.path)
    _invalidate_stats_cache(project_id)
    return {"id": im.id, "filename": im.filename,
            "width": im.width, "height": im.height,
            "annotation_count": 0, "is_deleted": False, "is_hard": False,
            "renamed_from": original_name if unique_name != original_name else None}

@app.post("/api/images/{image_id}/rename")
def rename_image(image_id: int, filename: str = Form(...), db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    raw = (filename or "").strip()
    validate_user_filename(raw)
    _, old_ext = _split_name_ext(img.filename)
    new_base, _ = _split_name_ext(raw)
    new_base = new_base.strip().rstrip('.')
    if not new_base:
        raise HTTPException(400, {"key": "error.emptyStem", "fallback": "Пустое имя файла"})
    new_name = new_base + (old_ext or '')
    if len(new_name) > 255:
        raise HTTPException(400, "Слишком длинное имя (макс. 255)")
    if INVALID_CHARS_RE.search(new_name):
        raise HTTPException(400, 'Недопустимые символы: \\ / : * ? " < > |')
    conflict = (db.query(ImageModel)
                  .filter(ImageModel.project_id == img.project_id,
                          ImageModel.is_deleted.is_(False),
                          ImageModel.id != img.id,
                          ImageModel.filename == new_name).first())
    if conflict:
        raise HTTPException(409, f"Имя «{new_name}» уже занято")
    img.filename = new_name
    db.commit()
    return {"id": img.id, "filename": img.filename}

@app.post("/api/images/{image_id}/toggle_hard")
def toggle_hard(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    img.is_hard = not bool(img.is_hard)
    db.commit()
    return {"id": img.id, "is_hard": bool(img.is_hard)}

@app.post("/api/images/{image_id}/reveal")
def reveal_image(image_id: int, db: Session = Depends(get_db)):
    """V8.1.0: открывает папку с файлом в системном проводнике."""
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    if not os.path.exists(img.path):
        raise HTTPException(404, {"key": "error.fileMissing", "fallback": "Файл отсутствует на диске"})
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(img.path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", img.path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(img.path)])
    except Exception as e:
        log.exception("reveal failed")
        raise HTTPException(500, f"Не удалось открыть проводник: {_safe_error_message(e)}")
    return {"status": "ok"}


@app.get("/api/images/{image_id}/thumb")
def get_image_thumb(image_id: int, db: Session = Depends(get_db)):
    row = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not row:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    p = ensure_thumb(row.id, row.path)
    if not p or not os.path.exists(p):
        raise HTTPException(500, "Cannot generate thumbnail")
    return FileResponse(p, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})

@app.get("/api/projects/{project_id}/images")
def list_images(project_id: int, offset: int = 0, limit: int = 0,
                sort: str = "name_asc", filter: str = "none",
                search: str = "", tag_ids: str = "",
                db: Session = Depends(get_db)):
    """V7.9.3: сортировка/фильтр/поиск/теги — на сервере.

    При limit>0 — отдаём страницу и totals. При limit=0 — всё (старое поведение).
    Для type_*/conf_* и фильтров unannotated/lowconf клиент просит limit=0
    (см. app.js → loadImages), чтобы сортировка была корректной.
    """
    # Парсинг tag_ids (CSV)
    parsed_tags = []
    if tag_ids:
        for t in tag_ids.split(","):
            try:
                parsed_tags.append(int(t.strip()))
            except (ValueError, TypeError):
                continue

    # Totals без фильтров — для прогресс-бара в сайдбаре
    project_total = int(db.query(func.count(ImageModel.id)).filter(
        ImageModel.project_id == project_id,
        ImageModel.is_deleted.is_(False),
    ).scalar() or 0)
    annotated_total = int(
        db.query(func.count(func.distinct(Annotation.image_id)))
          .join(ImageModel, Annotation.image_id == ImageModel.id)
          .filter(ImageModel.project_id == project_id,
                  ImageModel.is_deleted.is_(False))
          .scalar() or 0
    )

    # Базовый запрос
    q = db.query(ImageModel).filter(
        ImageModel.project_id == project_id,
        ImageModel.is_deleted.is_(False),
    )

    # Фильтр по поиску
    if search:
        q = q.filter(ImageModel.filename.ilike(f"%{search}%"))

    # Фильтр по тегам
    if parsed_tags:
        tag_subq = db.query(ImageTag.image_id).filter(
            ImageTag.tag_id.in_(parsed_tags)
        ).subquery()
        q = q.filter(ImageModel.id.in_(db.query(tag_subq.c.image_id)))

    # Фильтр по статусу
    if filter == "hard":
        q = q.filter(ImageModel.is_hard.is_(True))
    elif filter in ("unannotated", "lowconf"):
        stat_subq = db.query(
            Annotation.image_id.label("iid"),
            func.count(Annotation.id).label("cnt"),
            func.min(Annotation.confidence).label("min_conf"),
        ).group_by(Annotation.image_id).subquery()
        q = q.outerjoin(stat_subq, stat_subq.c.iid == ImageModel.id)
        if filter == "unannotated":
            q = q.filter(or_(stat_subq.c.cnt.is_(None), stat_subq.c.cnt == 0))
        else:
            q = q.filter(stat_subq.c.min_conf < 0.5)
    elif filter == "duplicates":
        # V8.0.0: id-шники дубликатов из TTL-кэша.
        dup_ids = _get_duplicate_ids_cached(project_id, db)
        if dup_ids:
            q = q.filter(ImageModel.id.in_(list(dup_ids)))
        else:
            q = q.filter(ImageModel.id.in_([-1]))

    filtered_total = int(q.count())

    # Сортировка (кроме type_* и conf_* — их клиент делает сам)
    # V8.1.1: name_/type_/conf_ сортирует КЛИЕНТ (natural sort).
    # Сервер упорядочивает только date_/size_ — эти безопасны
    # для пагинации (порядок стабилен при догрузке).
    if sort == "date_asc":
        q = q.order_by(ImageModel.created_at.asc())
    elif sort == "date_desc":
        q = q.order_by(ImageModel.created_at.desc())
    elif sort == "size_asc":
        q = q.order_by(ImageModel.file_size.asc())
    elif sort == "size_desc":
        q = q.order_by(ImageModel.file_size.desc())
    else:
        # name_*/type_*/conf_*/fallback: по id, клиент пересортирует
        q = q.order_by(ImageModel.id.asc())

    # Страница или всё
    if limit > 0:
        rows = q.offset(max(0, offset)).limit(min(limit, 5000)).all()
    else:
        rows = q.all()

    ids = [r.id for r in rows] or [0]
    raw_stats = db.query(
        Annotation.image_id.label("iid"),
        func.count(Annotation.id).label("cnt"),
        func.min(Annotation.confidence).label("min_conf"),
        func.avg(Annotation.confidence).label("avg_conf"),
        func.sum(case((Annotation.confidence < 0.5, 1), else_=0)).label("low_cnt"),
    ).filter(Annotation.image_id.in_(ids)).group_by(Annotation.image_id).all()
    stats = {s.iid: {"cnt": int(s.cnt or 0),
                     "min_conf": float(s.min_conf) if s.min_conf is not None else None,
                     "avg_conf": float(s.avg_conf) if s.avg_conf is not None else None,
                     "low_cnt": int(s.low_cnt or 0)}
             for s in raw_stats}

    tag_map = defaultdict(list)
    for it in db.query(ImageTag.image_id, ImageTag.tag_id).filter(
        ImageTag.image_id.in_(ids)).all():
        tag_map[it.image_id].append(it.tag_id)

    items = [{
        "id": r.id, "filename": r.filename, "width": r.width, "height": r.height,
        "annotation_count": stats.get(r.id, {}).get("cnt", 0),
        "is_deleted": False, "is_hard": bool(r.is_hard),
        "min_confidence": stats.get(r.id, {}).get("min_conf"),
        "avg_confidence": stats.get(r.id, {}).get("avg_conf"),
        "low_conf_count": stats.get(r.id, {}).get("low_cnt", 0),
        "tag_ids": tag_map.get(r.id, []),
        "video_id": r.video_id,
        "frame_index": r.frame_index,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "file_size": r.file_size,
    } for r in rows]

    if limit == 0:
        return items
    return {
        "items": items,
        "total": filtered_total,
        "offset": offset,
        "limit": limit,
        "project_total": project_total,
        "annotated_total": annotated_total,
    }

@app.get("/api/projects/{project_id}/trash")
def list_trash(project_id: int, db: Session = Depends(get_db)):
    rows = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(True))
              .order_by(ImageModel.deleted_at.desc(), ImageModel.id.desc()).all())
    ttl = get_trash_ttl_days(db)
    proj = db.query(Project).filter(Project.id == project_id).first()
    if proj and proj.trash_ttl_days_override is not None:
        ttl = proj.trash_ttl_days_override
    now = utcnow()
    out = []
    for r in rows:
        days_left = None
        if r.deleted_at and ttl > 0:
            days_left = max(0, (r.deleted_at + timedelta(days=ttl) - now).days)
        out.append({"id": r.id, "filename": r.filename,
                    "width": r.width, "height": r.height, "is_deleted": True,
                    "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
                    "days_left": days_left})
    return out

# V8.1.0: TTL-кэш статистики проекта.
_STATS_CACHE: dict = {}
_STATS_CACHE_LOCK = threading.Lock()
_STATS_CACHE_TTL = 30.0


def _invalidate_stats_cache(project_id: Optional[int] = None):
    with _STATS_CACHE_LOCK:
        if project_id is None:
            _STATS_CACHE.clear()
        else:
            _STATS_CACHE.pop(project_id, None)


def _compute_project_stats(project_id: int, db):
    total_q = (db.query(ImageModel.id)
                 .filter(ImageModel.project_id == project_id,
                         ImageModel.is_deleted.is_(False)))
    total = total_q.count()
    if total == 0:
        return {"total_images": 0, "annotated_images": 0, "unannotated_images": 0,
                "total_boxes": 0, "avg_boxes": 0.0,
                "confidence": {"manual": 0, "low": 0, "mid": 0, "high": 0},
                "top_suspicious": [], "unannotated_sample": []}
    ids_subq = total_q.subquery()
    agg = db.query(
        func.count(Annotation.id).label("cnt"),
        func.sum(case((Annotation.confidence.is_(None), 1), else_=0)).label("manual"),
        func.sum(case((Annotation.confidence < 0.5, 1), else_=0)).label("low"),
        func.sum(case((((Annotation.confidence >= 0.5) & (Annotation.confidence < 0.75)), 1), else_=0)).label("mid"),
        func.sum(case((Annotation.confidence >= 0.75, 1), else_=0)).label("high"),
    ).filter(Annotation.image_id.in_(ids_subq)).one()
    total_boxes = int(agg.cnt or 0)
    manual = int(agg.manual or 0)
    low = int(agg.low or 0)
    mid = int(agg.mid or 0)
    high = int(agg.high or 0)
    per_rows = (db.query(Annotation.image_id, func.count(Annotation.id),
                          func.min(Annotation.confidence))
                  .filter(Annotation.image_id.in_(ids_subq))
                  .group_by(Annotation.image_id).all())
    per = {iid: cnt for iid, cnt, _ in per_rows}
    min_conf_by_img = {iid: mc for iid, _, mc in per_rows}
    annotated = len(per)
    suspicious_sorted = sorted(
        per.items(),
        key=lambda x: (min_conf_by_img.get(x[0]) if min_conf_by_img.get(x[0]) is not None else 1.0)
    )[:10]
    unannotated_ids_q = (db.query(ImageModel.id)
                           .filter(ImageModel.project_id == project_id,
                                   ImageModel.is_deleted.is_(False)))
    if per:
        unannotated_ids_q = unannotated_ids_q.filter(~ImageModel.id.in_(per.keys()))
    unannotated_ids = [iid for (iid,) in unannotated_ids_q.limit(20).all()]
    wanted_ids = list({iid for iid, _ in suspicious_sorted} | set(unannotated_ids))
    metas = {}
    if wanted_ids:
        metas = {im.id: im for im in db.query(ImageModel)
                                         .filter(ImageModel.id.in_(wanted_ids)).all()}
    top_suspicious = []
    for iid, cnt in suspicious_sorted:
        im = metas.get(iid)
        if not im:
            continue
        top_suspicious.append({
            "id": im.id, "filename": im.filename,
            "annotation_count": cnt,
            "min_confidence": min_conf_by_img.get(iid),
        })
    unannotated_sample = []
    for iid in unannotated_ids:
        im = metas.get(iid)
        if im:
            unannotated_sample.append({"id": im.id, "filename": im.filename})
    return {
        "total_images": total, "annotated_images": annotated,
        "unannotated_images": total - annotated,
        "total_boxes": total_boxes,
        "avg_boxes": (total_boxes / annotated) if annotated else 0.0,
        "confidence": {"manual": manual, "low": low, "mid": mid, "high": high},
        "top_suspicious": top_suspicious,
        "unannotated_sample": unannotated_sample,
    }


@app.get("/api/projects/{project_id}/stats")
def project_stats(project_id: int, db: Session = Depends(get_db)):
    """V8.1.0: кэш 30 секунд. Инвалидация — из write-эндпоинтов."""
    now = time.monotonic()
    with _STATS_CACHE_LOCK:
        cached = _STATS_CACHE.get(project_id)
        if cached and (now - cached[0]) < _STATS_CACHE_TTL:
            return cached[1]
    data = _compute_project_stats(project_id, db)
    with _STATS_CACHE_LOCK:
        _STATS_CACHE[project_id] = (now, data)
    return data


@app.get("/api/projects/{project_id}/stats.csv")
def export_stats_csv(project_id: int, filter: str = "none", search: str = "",
                     tag_ids: str = "", db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})

    # V8.0.0: активные фильтры применяются и к CSV-экспорту.
    parsed_tags = []
    if tag_ids:
        for t in tag_ids.split(","):
            try:
                parsed_tags.append(int(t.strip()))
            except (ValueError, TypeError):
                continue

    q = db.query(ImageModel).filter(
        ImageModel.project_id == project_id,
        ImageModel.is_deleted.is_(False),
    )
    if search:
        q = q.filter(ImageModel.filename.ilike(f"%{search}%"))
    if parsed_tags:
        tag_subq = db.query(ImageTag.image_id).filter(
            ImageTag.tag_id.in_(parsed_tags)
        ).subquery()
        q = q.filter(ImageModel.id.in_(db.query(tag_subq.c.image_id)))
    if filter == "hard":
        q = q.filter(ImageModel.is_hard.is_(True))
    elif filter in ("unannotated", "lowconf"):
        stat_subq = db.query(
            Annotation.image_id.label("iid"),
            func.count(Annotation.id).label("cnt"),
            func.min(Annotation.confidence).label("min_conf"),
        ).group_by(Annotation.image_id).subquery()
        q = q.outerjoin(stat_subq, stat_subq.c.iid == ImageModel.id)
        if filter == "unannotated":
            q = q.filter(or_(stat_subq.c.cnt.is_(None), stat_subq.c.cnt == 0))
        else:
            q = q.filter(stat_subq.c.min_conf < 0.5)
    elif filter == "duplicates":
        dup_ids = _get_duplicate_ids_cached(project_id, db)
        if dup_ids:
            q = q.filter(ImageModel.id.in_(list(dup_ids)))
        else:
            q = q.filter(ImageModel.id.in_([-1]))

    imgs = q.order_by(ImageModel.id).all()
    ids = [r.id for r in imgs] or [0]
    stats_rows = db.query(
        Annotation.image_id, func.count(Annotation.id),
        func.min(Annotation.confidence), func.avg(Annotation.confidence),
        func.sum(case((Annotation.confidence < 0.5, 1), else_=0)),
    ).filter(Annotation.image_id.in_(ids)).group_by(Annotation.image_id).all()
    stats = {s[0]: s for s in stats_rows}
    tag_ids_by_image = defaultdict(list)
    for it in db.query(ImageTag.image_id, ImageTag.tag_id).filter(
        ImageTag.image_id.in_(ids)).all():
        tag_ids_by_image[it.image_id].append(it.tag_id)
    tag_name_by_id = {t.id: t.name for t in db.query(Tag).filter(Tag.project_id == project_id).all()}
    buf = StringIO()
    w = csv.writer(buf, delimiter=';', lineterminator='\n')
    w.writerow(["image_id", "filename", "annotation_count", "min_confidence",
                "avg_confidence", "low_conf_count", "is_hard", "tags"])
    for r in imgs:
        s = stats.get(r.id)
        cnt = int(s[1]) if s else 0
        min_conf = f"{float(s[2]):.3f}" if s and s[2] is not None else ""
        avg_conf = f"{float(s[3]):.3f}" if s and s[3] is not None else ""
        low_cnt = int(s[4]) if s and s[4] is not None else 0
        tag_names = ";".join(tag_name_by_id.get(tid, "") for tid in tag_ids_by_image.get(r.id, []))
        w.writerow([r.id, r.filename, cnt, min_conf, avg_conf, low_cnt,
                    1 if r.is_hard else 0, tag_names])
    csv_bytes = buf.getvalue().encode("utf-8-sig")
    return Response(content=csv_bytes, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=stats_project_{project_id}.csv"})

@app.get("/api/projects/{project_id}/boxes.csv")
def export_boxes_csv(project_id: int, db: Session = Depends(get_db)):
    """V8.1.0: экспорт всех рамок проекта (не только статистики)."""
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    rows = (db.query(Annotation, ImageModel)
              .join(ImageModel, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False))
              .order_by(ImageModel.id, Annotation.id)
              .all())
    buf = StringIO()
    w = csv.writer(buf, delimiter=';', lineterminator='\n')
    w.writerow(["image_id", "filename", "annotation_id",
                "x", "y", "w", "h", "label", "confidence",
                "is_frozen", "x_px", "y_px", "w_px", "h_px"])
    for a, im in rows:
        xp = a.x * (im.width or 0)
        yp = a.y * (im.height or 0)
        wp = a.w * (im.width or 0)
        hp = a.h * (im.height or 0)
        w.writerow([
            im.id, im.filename, a.id,
            f"{a.x:.6f}", f"{a.y:.6f}", f"{a.w:.6f}", f"{a.h:.6f}",
            a.label, "" if a.confidence is None else f"{a.confidence:.4f}",
            1 if a.is_frozen else 0,
            f"{xp:.2f}", f"{yp:.2f}", f"{wp:.2f}", f"{hp:.2f}",
        ])
    csv_bytes = buf.getvalue().encode("utf-8-sig")
    log_status("info", "export", f"CSV боксов проекта #{project_id}: {len(rows)} строк")
    return Response(content=csv_bytes, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=boxes_project_{project_id}.csv"})


@app.get("/api/projects/{project_id}/files.csv")
def project_files_csv(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    imgs = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False))
              .order_by(ImageModel.id).all())
    ids = [im.id for im in imgs] or [0]
    ann_counts = dict(
        db.query(Annotation.image_id, func.count(Annotation.id))
          .filter(Annotation.image_id.in_(ids))
          .group_by(Annotation.image_id).all()
    )
    buf = StringIO()
    w = csv.writer(buf, delimiter=';', lineterminator='\n')
    w.writerow(["image_id", "filename", "file_size_bytes", "width", "height",
                "annotation_count", "video_id", "frame_index",
                "created_at", "is_hard", "phash"])
    for im in imgs:
        w.writerow([
            im.id, im.filename, im.file_size or "",
            im.width, im.height, int(ann_counts.get(im.id, 0)),
            im.video_id or "", im.frame_index if im.frame_index is not None else "",
            im.created_at.isoformat() if im.created_at else "",
            1 if im.is_hard else 0, im.phash or "",
        ])
    csv_bytes = buf.getvalue().encode("utf-8-sig")
    return Response(content=csv_bytes, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=files_project_{project_id}.csv"})

def _pairs_of_overlapping(boxes):
    n = len(boxes)
    if n < 2:
        return
    order = sorted(range(n), key=lambda k: boxes[k].x)
    active = []
    for i_idx in order:
        a = boxes[i_idx]
        active = [k for k in active if (boxes[k].x + boxes[k].w) > a.x]
        for k in active:
            yield (k, i_idx)
        active.append(i_idx)

@app.get("/api/projects/{project_id}/validate")
def validate_project(project_id: int, deep: bool = True, db: Session = Depends(get_db)):
    imgs = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False)).all())
    if not imgs:
        return {"issues": [], "by_type": {}, "unannotated": [], "total_issues": 0}
    ids = [r.id for r in imgs]
    anns = db.query(Annotation).filter(Annotation.image_id.in_(ids)).all()
    by_image = defaultdict(list)
    for a in anns:
        by_image[a.image_id].append(a)
    issues = []
    def add_issue(typ, image, detail, ann=None):
        issues.append({"type": typ, "image_id": image.id, "filename": image.filename,
                       "detail": detail, "annotation_id": ann.id if ann else None})
    unannotated = []
    MAX_PAIRS_PER_IMAGE = 200
    for img_idx, img in enumerate(imgs):
        boxes = by_image.get(img.id, [])
        if not boxes:
            unannotated.append({"id": img.id, "filename": img.filename})
            continue
        for a in boxes:
            area = a.w * a.h
            if area < MIN_BOX_AREA:
                add_issue("small_box", img, f"Площадь {area*100:.2f}% < {MIN_BOX_AREA*100:.2f}%", a)
            if a.x < -0.001 or a.y < -0.001 or a.x + a.w > 1.001 or a.y + a.h > 1.001:
                add_issue("out_of_bounds", img, f"x={a.x:.3f}, y={a.y:.3f}, w={a.w:.3f}, h={a.h:.3f}", a)
            if a.w > 0 and a.h > 0:
                ar = a.w / a.h
                if ar < 1.0 / MAX_ASPECT or ar > MAX_ASPECT:
                    add_issue("aspect", img, f"Аспект {ar:.2f}", a)
        boxes_for_overlap = boxes[:MAX_PAIRS_PER_IMAGE]
        for i_idx, j_idx in _pairs_of_overlapping(boxes_for_overlap):
            a, b = boxes_for_overlap[i_idx], boxes_for_overlap[j_idx]
            iou = _iou_xywh({"x": a.x, "y": a.y, "w": a.w, "h": a.h},
                            {"x": b.x, "y": b.y, "w": b.w, "h": b.h})
            if iou > MAX_OVERLAP_IOU:
                add_issue("overlap", img, f"IoU {iou:.2f} между #{a.id} и #{b.id}", a)
            def inside(inner, outer):
                return (outer.x <= inner.x and outer.y <= inner.y and
                        outer.x + outer.w >= inner.x + inner.w and
                        outer.y + outer.h >= inner.y + inner.h)
            if inside(b, a) and (b.w * b.h) < NESTED_RATIO * (a.w * a.h):
                add_issue("nested_box", img, f"Рамка #{b.id} внутри #{a.id}", b)
            elif inside(a, b) and (a.w * a.h) < NESTED_RATIO * (b.w * b.h):
                add_issue("nested_box", img, f"Рамка #{a.id} внутри #{b.id}", a)
    by_type = defaultdict(int)
    for i in issues:
        by_type[i["type"]] += 1
    return {"issues": issues[:500], "by_type": dict(by_type),
            "unannotated": unannotated[:200], "total_issues": len(issues)}

@app.get("/api/images/{image_id}/file")
def get_image_file(image_id: int, db: Session = Depends(get_db)):
    row = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not row:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    return FileResponse(row.path)

@app.delete("/api/images/{image_id}")
def soft_delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    if img.is_deleted:
        return {"status": "ok", "deleted_id": image_id, "soft": True, "already_deleted": True}
    img.is_deleted = True
    img.deleted_at = utcnow()
    db.commit()
    return {"status": "ok", "deleted_id": image_id, "soft": True}

@app.delete("/api/images/{image_id}/permanent")
def permanent_delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    file_path = img.path
    db.delete(img)
    db.commit()
    _remove_file_safe(file_path)
    _remove_thumb(image_id)
    return {"status": "ok", "deleted_id": image_id, "permanent": True}

@app.post("/api/images/batch_delete")
def batch_delete_images(ids: list = Body(...), db: Session = Depends(get_db)):
    if not ids:
        return {"deleted": 0}
    now = utcnow()
    rows = db.query(ImageModel).filter(ImageModel.id.in_(ids)).all()
    changed = 0
    for r in rows:
        if r.is_deleted:
            continue
        r.is_deleted = True
        r.deleted_at = now
        changed += 1
    db.commit()
    return {"deleted": changed, "ids": [r.id for r in rows]}

@app.post("/api/images/batch_restore")
def batch_restore_images(ids: list = Body(...), db: Session = Depends(get_db)):
    if not ids:
        return {"restored": 0, "renamed": 0}
    rows = db.query(ImageModel).filter(ImageModel.id.in_(ids)).all()
    by_project = defaultdict(set)
    pending = defaultdict(set)
    total_renamed = 0
    restored_count = 0
    restored_ids = []
    for r in rows:
        if not r.is_deleted:
            continue
        restored_count += 1
        restored_ids.append(r.id)
        pid = r.project_id
        if pid not in by_project:
            used = {n for (n,) in db.query(ImageModel.filename).filter(
                ImageModel.project_id == pid,
                ImageModel.is_deleted.is_(False),
            ).all()}
            by_project[pid] = used
        used = by_project[pid] | pending[pid]
        new_name = r.filename
        if new_name in used:
            base, ext = _split_name_ext(new_name)
            m = re.match(r'^(.*) \((\d+)\)$', base)
            base_root = m.group(1) if m else base
            max_n = 0
            for ex in used:
                e_base, e_ext = _split_name_ext(ex)
                if e_ext.lower() != ext.lower():
                    continue
                m2 = re.match(r'^' + re.escape(base_root) + r' \((\d+)\)$', e_base)
                if m2:
                    max_n = max(max_n, int(m2.group(1)))
            new_name = f"{base_root} ({max_n + 1}){ext}"
            total_renamed += 1
        pending[pid].add(new_name)
        r.filename = new_name
        r.is_deleted = False
        r.deleted_at = None
    db.commit()
    return {"restored": restored_count, "renamed": total_renamed, "ids": restored_ids}

@app.post("/api/images/batch_permanent_delete")
def batch_permanent_delete_images(ids: list = Body(...), db: Session = Depends(get_db)):
    if not ids:
        return {"deleted": 0}
    rows = db.query(ImageModel).filter(ImageModel.id.in_(ids)).all()
    paths = [r.path for r in rows]
    for r in rows:
        db.delete(r)
    db.commit()
    for p in paths:
        _remove_file_safe(p)
    for iid in ids:
        _remove_thumb(iid)
    return {"deleted": len(rows), "ids": ids}

@app.post("/api/projects/{project_id}/trash/empty")
def empty_trash(project_id: int, db: Session = Depends(get_db)):
    rows = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(True)).all())
    paths = [r.path for r in rows]
    ids = [r.id for r in rows]
    for r in rows:
        db.delete(r)
    db.commit()
    for p in paths:
        _remove_file_safe(p)
    for iid in ids:
        _remove_thumb(iid)
    log_status("warning", "trash", f"Корзина проекта #{project_id} очищена: {len(rows)}")
    return {"status": "ok", "deleted": len(rows)}

@app.post("/api/images/{image_id}/restore")
def restore_image(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    if not img.is_deleted:
        return {"status": "ok", "restored_id": image_id,
                "filename": img.filename, "already_active": True}
    img.filename = make_unique_filename(db, img.project_id, img.filename, exclude_id=img.id)
    img.is_deleted = False
    img.deleted_at = None
    db.commit()
    return {"status": "ok", "restored_id": image_id, "filename": img.filename}

@app.get("/api/images/{image_id}/annotations")
def get_annotations(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    rows = db.query(Annotation).filter(Annotation.image_id == image_id).all()
    return [{"x": a.x, "y": a.y, "w": a.w, "h": a.h,
             "label": a.label, "confidence": a.confidence,
             "frozen": bool(a.is_frozen)} for a in rows]

@app.post("/api/images/{image_id}/annotations")
def save_annotations(image_id: int, annotations: list[AnnotationIn],
                     db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    db.query(Annotation).filter(Annotation.image_id == image_id).delete()
    for a in annotations:
        db.add(Annotation(image_id=image_id,
                          x=a.x, y=a.y, w=a.w, h=a.h,
                          label=a.label, confidence=a.confidence,
                          is_frozen=bool(a.frozen)))
    db.commit()
    _invalidate_stats_cache(img.project_id)
    return {"status": "ok", "count": len(annotations)}

@app.post("/api/images/{image_id}/autolabel")
def autolabel(image_id: int, payload: AutolabelIn = Body(default_factory=AutolabelIn), db: Session = Depends(get_db)):
    _rate_limit(_limiter_autolabel, "local", {"key": "error.rateLimitedAutolabel", "fallback": "Слишком много авторазметок. Подожди минуту."})
    model_path = get_active_model_path(db)
    if not model_path:
        raise HTTPException(501, {"key": "error.noModel", "fallback": "Активная модель не найдена"})
    try:
        model = _get_yolo_model(model_path)
    except ImportError:
        raise HTTPException(501, "ultralytics не установлен")
    except Exception as e:
        raise HTTPException(500, f"Ошибка загрузки модели: {_safe_error_message(e)}")
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    project = db.query(Project).filter(Project.id == img.project_id).first()
    if not project:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    return _autolabel_image_with_model(
        db, img, model, project,
        tta=bool(payload.tta), mode=_norm_mode(payload.mode),
    )

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
        raise HTTPException(501, "ultralytics не установлен")
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
                "is_target": (not target_ids) or (cls_id in target_ids),
            }
            detections.append(det)
            if det["is_target"]:
                target_detections.append({
                    "x": det["x"], "y": det["y"], "w": det["w"], "h": det["h"],
                    "label": target_label,
                    "confidence": bconf,
                })

    target_dedup = dedup_boxes(target_detections)
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
                           confidence=a["confidence"], is_frozen=False)
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
                       confidence=a["confidence"], is_frozen=False)
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
            for a in anns:
                db.add(Annotation(image_id=new_im.id,
                                  x=a.x, y=a.y, w=a.w, h=a.h,
                                  label=dst_class, confidence=a.confidence,
                                  is_frozen=a.is_frozen))
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
    rows = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash,
                     ImageModel.file_size, ImageModel.width, ImageModel.height)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False),
                      ImageModel.phash.isnot(None))
              .all())
    if len(rows) < 2:
        return {"groups": [], "total": 0}
    buckets = defaultdict(list)
    for r in rows:
        if r.phash and len(r.phash) >= 4:
            buckets[r.phash[:4]].append(r)
    parent = {r.id: r.id for r in rows}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    keys = list(buckets.keys())
    for i, k in enumerate(keys):
        for r1 in buckets[k]:
            for r2 in buckets[k]:
                if r1.id >= r2.id:
                    continue
                if hamming_hex(r1.phash, r2.phash) <= threshold:
                    union(r1.id, r2.id)
            for k2 in keys[i+1:i+6]:
                for r2 in buckets[k2]:
                    if hamming_hex(r1.phash, r2.phash) <= threshold:
                        union(r1.id, r2.id)
    groups_map = defaultdict(list)
    for r in rows:
        groups_map[find(r.id)].append(r)
    out = []
    for gid, items in groups_map.items():
        if len(items) < 2:
            continue
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
def _process_dataset_zip(zip_path: str, project_id: int, db) -> dict:
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
            raise HTTPException(400, "Файл не является zip-архивом")

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
                by_stem[stem_x] = im_x
            pending = []

        for img_path in image_files_peek:
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

        parsed = {}
        if fmt == "coco":
            parsed = parse_coco(src, default_label=project_class)
        elif fmt == "yolo":
            parsed = parse_yolo(tmp_dir, default_label=project_class)
        elif fmt == "cvat":
            parsed = parse_cvat(src, default_label=project_class)
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
                anns_to_add.append(Annotation(
                    image_id=im.id,
                    x=max(0.0, min(1.0, b["x"])),
                    y=max(0.0, min(1.0, b["y"])),
                    w=max(0.0, min(1.0, b["w"])),
                    h=max(0.0, min(1.0, b["h"])),
                    label=project_class,
                    confidence=b.get("confidence"),
                    is_frozen=False,
                ))
                added_anns += 1
            matched += 1

        if image_ids_to_clear:
            db.query(Annotation).filter(
                Annotation.image_id.in_(image_ids_to_clear)
            ).delete(synchronize_session=False)
        if anns_to_add:
            db.bulk_save_objects(anns_to_add)
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

@app.post("/api/projects/{project_id}/import")
def import_annotations(project_id: int, file: UploadFile = File(...),
                       db: Session = Depends(get_db)):
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
        return _process_dataset_zip(tmp_zip, project_id, db)
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
            return _process_dataset_zip(tmp_zip, project_id, db)
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
            return _process_dataset_zip(tmp_zip, project_id, db)
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
    if ids:
        rows = db.query(Annotation).filter(Annotation.image_id.in_(ids)).all()
        for a in rows:
            annotations[str(a.image_id)].append({
                "x": a.x, "y": a.y, "w": a.w, "h": a.h,
                "label": a.label, "confidence": a.confidence,
                "frozen": bool(a.is_frozen),
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
        raise HTTPException(400, "Некорректный путь")
    if not os.path.exists(real):
        raise HTTPException(404, "Файл не найден")
    return FileResponse(real, filename=filename, media_type="application/zip")

# ---------------------------------------------------------------------------
# Экспорт
# ---------------------------------------------------------------------------
def _split_images(images, split_spec):
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
        raise HTTPException(404, "No images")
    buckets = _split_images(images, split)
    use_split = split and split != "none" and (len(buckets["val"]) + len(buckets["test"])) > 0
    zip_path = os.path.join(EXPORT_DIR, f"yolo_project_{project_id}_{naming}_{split}.zip")
    used = set()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        if use_split:
            data_yaml = (f"path: .\ntrain: images/train\nval: images/val\n"
                         f"test: images/test\nnc: 1\nnames: ['{class_yaml}']\n")
        else:
            data_yaml = (f"path: .\ntrain: images\nval: images\n"
                         f"nc: 1\nnames: ['{class_yaml}']\n")
        z.writestr("data.yaml", data_yaml)
        for bucket_name, bucket_images in buckets.items():
            if not bucket_images:
                continue
            sub_img = f"images/{bucket_name}" if use_split else "images"
            sub_lbl = f"labels/{bucket_name}" if use_split else "labels"
            for img in bucket_images:
                iname = _iname_for_export(img, naming, used)
                z.write(img.path, f"{sub_img}/{iname}")
                anns = db.query(Annotation).filter(Annotation.image_id == img.id).all()
                lines = [f"0 {a.x:.6f} {a.y:.6f} {a.w:.6f} {a.h:.6f}" for a in anns]
                z.writestr(f"{sub_lbl}/{os.path.splitext(iname)[0]}.txt", "\n".join(lines))
    suffix = "orig" if naming == "original" else "num"
    suffix += "_split" if use_split else ""
    _cleanup_old_exports("yolo_project_")
    log_status("info", "export",
               f"Экспорт YOLO проекта #{project_id} (класс «{object_class}»): {len(images)} фото")
    return FileResponse(zip_path, filename=f"yolo_project_{project_id}_{suffix}.zip",
                        media_type="application/zip")

@app.get("/api/projects/{project_id}/export/coco")
def export_coco(project_id: int, naming: str = "numbered", split: str = "none",
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
        raise HTTPException(404, "No images")
    buckets = _split_images(images, split)
    use_split = split and split != "none" and (len(buckets["val"]) + len(buckets["test"])) > 0
    zip_path = os.path.join(EXPORT_DIR, f"coco_project_{project_id}_{naming}_{split}.zip")
    used = set()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for bucket_name, bucket_images in buckets.items():
            if not bucket_images:
                continue
            sub = f"images/{bucket_name}" if use_split else "images"
            coco = {"images": [], "annotations": [],
                    "categories": [{"id": 1, "name": object_class}]}
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
                    coco["annotations"].append(ann)
                    ann_id += 1
                z.write(img.path, f"{sub}/{iname}")
            z.writestr(f"coco_{bucket_name}.json", json.dumps(coco, ensure_ascii=False, indent=2))
    suffix = "orig" if naming == "original" else "num"
    suffix += "_split" if use_split else ""
    _cleanup_old_exports("coco_project_")
    log_status("info", "export",
               f"Экспорт COCO проекта #{project_id} (класс «{object_class}»): {len(images)} фото")
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
@app.get("/api/version")
def api_version():
    return {"version": APP_VERSION, "author": AUTHOR}


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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")