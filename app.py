"""
Dataset Builder — V7.0.1
============================================================
Backend: FastAPI + MySQL + YOLO.
Frontend: index.html + style.css + app.js (лежат рядом, отдаются как статика).

Запуск:
    1) CREATE DATABASE pig_dataset CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    2) pip install -r requirements.txt
    3) python run.py
Открыть: http://localhost:8000
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
import random
import shutil
import zipfile
import tempfile
import threading
import subprocess
import asyncio
import logging
import warnings
import urllib.request
import uvicorn

import xml.etree.ElementTree as ET

from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Depends, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, Response, JSONResponse
from pydantic import BaseModel, Field, field_validator
from PIL import Image

Image.MAX_IMAGE_PIXELS = 50_000_000

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, ForeignKey,
    Boolean, DateTime, inspect, text, UniqueConstraint, Index, func, case
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("db")

try:
    warnings.simplefilter('error', Image.DecompressionBombWarning)
except Exception:
    pass

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------
# V7.0.0: мажорный бамп, приложение теперь мультиклассовое
APP_VERSION = "V7.0.1"
AUTHOR = "Xulkvan"

DEBUG_MODE = os.getenv("DEBUG", "0") == "1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
IMPORT_DIR = os.path.join(BASE_DIR, "imports")
MODEL_DIR = os.path.join(BASE_DIR, "models")
RUNS_DIR = os.path.join(BASE_DIR, "runs")
THUMB_DIR = os.path.join(BASE_DIR, "thumbs")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")
STYLE_CSS_PATH = os.path.join(BASE_DIR, "style.css")
APP_JS_PATH = os.path.join(BASE_DIR, "app.js")

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

# V7.0.0: дефолтный класс проекта и максимальная длина имени класса
DEFAULT_OBJECT_CLASS = "pig"
MAX_OBJECT_CLASS_LEN = 128

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

# V7.0.0: PIG_CLASS_NAMES удалён — класс берётся из project.object_class
IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".webp",
    ".tif", ".tiff", ".avif", ".heic", ".heif", ".gif",
})

YOLO_RELEASE_TAG = "v8.3.0"
YOLO_URL_TEMPLATE = "https://github.com/ultralytics/assets/releases/download/{tag}/{name}"

for d in (UPLOAD_DIR, EXPORT_DIR, MODEL_DIR, IMPORT_DIR, RUNS_DIR, THUMB_DIR, BACKUP_DIR):
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
# MySQL
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

if DB_PASSWORD == "root":
    log.warning("Используется пароль MySQL по умолчанию 'root'. "
                "Задай DB_PASSWORD через переменную окружения или .env.")

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
    # V7.0.0: класс объекта детекции для проекта + источник
    object_class = Column(String(128), nullable=False, default=DEFAULT_OBJECT_CLASS,
                          server_default=DEFAULT_OBJECT_CLASS)
    object_class_source = Column(String(16), nullable=False, default="list",
                                 server_default="list")
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


# ---------------------------------------------------------------------------
# Pydantic-схемы
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


class DownloadModelIn(BaseModel):
    size: str = "n"
    pretrain: str = "oiv7"
    custom_name: str = ""


class BatchTagsIn(BaseModel):
    image_ids: list[int] = Field(default_factory=list)
    add: list[int] = Field(default_factory=list)
    remove: list[int] = Field(default_factory=list)


# V7.0.0: Pydantic-схема для PATCH /settings
class ProjectSettingsIn(BaseModel):
    object_class: str
    object_class_source: str = "list"


# ---------------------------------------------------------------------------
# Миграция — V7.0.0 добавил Project.object_class / object_class_source
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
    # V7.0.0
    ("projects", "object_class",
     f"VARCHAR(128) NOT NULL DEFAULT '{DEFAULT_OBJECT_CLASS}'"),
    ("projects", "object_class_source",
     "VARCHAR(16) NOT NULL DEFAULT 'list'"),
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
                conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}"))
            log.info("migrate: %s.%s added", table, column)
        except Exception:
            log.exception("migrate: %s.%s failed", table, column)

    # Индекс на projects после добавления колонок
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


ensure_schema()
Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# Настройки / пути / цвет
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
        raise HTTPException(400, "Некорректное имя модели")
    if not _MODEL_NAME_RE.match(name):
        raise HTTPException(400, "Некорректное имя модели")

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
        if not real.startswith(os.path.realpath(BASE_DIR) + os.sep):
            log.debug("skip removal outside base dir: %s", p)
            return
        if os.path.isfile(real):
            os.remove(real)
    except OSError as e:
        log.warning("cannot remove %s: %s", p, e)
    except Exception:
        log.exception("unexpected error removing %s", p)


# ---------------------------------------------------------------------------
# V7.0.0: object_class helpers
# ---------------------------------------------------------------------------
def _validate_object_class(name: str) -> str:
    """Нормализует и валидирует класс объекта для проекта."""
    n = (name or "").strip()
    if not n:
        raise HTTPException(400, "Имя класса не может быть пустым")
    if len(n) > MAX_OBJECT_CLASS_LEN:
        raise HTTPException(400, f"Слишком длинное имя класса (макс. {MAX_OBJECT_CLASS_LEN})")
    # Разрешаем буквы/цифры/пробел/дефис/подчёркивание/точку/апостроф/скобки
    if not re.match(r"^[\w\s\-\.'\(\)/]+$", n, flags=re.UNICODE):
        raise HTTPException(400, "Недопустимые символы в имени класса")
    return n


def _validate_object_class_source(src: str) -> str:
    s = (src or "").strip().lower()
    if s not in ("list", "custom"):
        return "list"
    return s


def _resolve_target_class_ids(model, object_class: str) -> set:
    """
    Возвращает множество id классов в модели, которые соответствуют
    выбранному object_class (точное совпадение без учёта регистра и пробелов).
    """
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
    """Возвращает отсортированный список классов модели."""
    names = getattr(model, "names", {}) or {}
    result = []
    for cid, cname in names.items():
        try:
            cn = str(cname).strip()
        except Exception:
            continue
        if cn:
            result.append(cn)
    # uniq по case-insensitive, сохраняем первый вариант написания
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
# Корзина
# ---------------------------------------------------------------------------
def _purge_projects(db, project_ids: list[int]) -> int:
    """Полное удаление проектов с диска и из БД. Возвращает число удалённых."""
    if not project_ids:
        return 0

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
    db.query(Tag).filter(Tag.project_id.in_(project_ids)).delete(synchronize_session=False)
    db.query(Project).filter(Project.id.in_(project_ids)).delete(synchronize_session=False)
    db.commit()

    for p in img_paths:
        _remove_file_safe(p)
    for iid in img_ids:
        _remove_thumb(iid)

    log_status("warning", "trash", f"Полностью удалено проектов: {len(project_ids)}, "
                                   f"файлов: {len(img_paths)}")
    return len(project_ids)


def cleanup_expired_trash(db) -> int:
    ttl = get_trash_ttl_days(db)
    if ttl <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=ttl)
    total = 0

    while True:
        rows = (db.query(Project.id)
                  .filter(Project.is_deleted.is_(True),
                          Project.deleted_at.isnot(None),
                          Project.deleted_at < cutoff)
                  .limit(50).all())
        if not rows:
            break
        ids = [r.id for r in rows]
        _purge_projects(db, ids)
        total += len(ids)
        if len(rows) < 50:
            break

    CHUNK = 500
    while True:
        rows = (db.query(ImageModel.id, ImageModel.path)
                  .filter(ImageModel.is_deleted.is_(True),
                          ImageModel.deleted_at.isnot(None),
                          ImageModel.deleted_at < cutoff)
                  .limit(CHUNK).all())
        if not rows:
            break

        ids = [r.id for r in rows]
        paths = [r.path for r in rows]

        db.query(Annotation).filter(Annotation.image_id.in_(ids)).delete(synchronize_session=False)
        db.query(ImageTag).filter(ImageTag.image_id.in_(ids)).delete(synchronize_session=False)
        db.query(ImageModel).filter(ImageModel.id.in_(ids)).delete(synchronize_session=False)
        db.commit()

        for p in paths:
            _remove_file_safe(p)
        for iid in ids:
            _remove_thumb(iid)

        total += len(rows)
        if len(rows) < CHUNK:
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
# Скачивание моделей + bootstrap
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


def find_duplicate(db, project_id: int, phash: str):
    if not phash or len(phash) < 4:
        return None

    bucket = phash[:4]
    rows = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False),
                      ImageModel.phash.isnot(None),
                      ImageModel.phash.like(f"{bucket}%"))
              .all())
    for r in rows:
        if hamming_hex(phash, r.phash) <= PHASH_DUPLICATE_THRESHOLD:
            return r

    if len(rows) < 4:
        rest = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
                  .filter(ImageModel.project_id == project_id,
                          ImageModel.is_deleted.is_(False),
                          ImageModel.phash.isnot(None),
                          ~ImageModel.phash.like(f"{bucket}%"))
                  .limit(500).all())
        for r in rest:
            if hamming_hex(phash, r.phash) <= PHASH_DUPLICATE_THRESHOLD:
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
        raise HTTPException(400, "Слишком длинное имя (макс. 200 символов)")
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
            raise HTTPException(
                413,
                f"Распакованный архив превышает {MAX_EXTRACTED_MB} МБ"
            )
        if member.compress_size > 0 and member.file_size > 10 * 1024 * 1024:
            ratio = member.file_size / member.compress_size
            if ratio > 1000:
                raise HTTPException(
                    400,
                    f"Подозрительная компрессия (ratio={ratio:.0f}): {name}"
                )

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
# Авторазметка — V7.0.0: класс берётся из проекта
# ---------------------------------------------------------------------------
_YOLO_CACHE = {}
_YOLO_CACHE_LOCK = threading.Lock()


def _get_yolo_model(model_path: str):
    with _YOLO_CACHE_LOCK:
        m = _YOLO_CACHE.get(model_path)
        if m is not None:
            return m
    from ultralytics import YOLO
    m = YOLO(model_path)
    with _YOLO_CACHE_LOCK:
        _YOLO_CACHE.clear()
        _YOLO_CACHE[model_path] = m
    return m


def _autolabel_image_predict(img_path: str, model, W: int, H: int,
                              target_class_ids: set,
                              target_label: str,
                              conf: float = None):
    """
    V7.0.0: target_class_ids — множество id допустимых классов в модели,
    target_label — метка, которая будет присвоена найденным рамкам.
    """
    if conf is None:
        conf = CONF_THRESHOLD
    results = model(img_path, conf=conf, verbose=False)
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


def _load_annotations(db, image_id: int) -> list:
    rows = (db.query(Annotation)
              .filter(Annotation.image_id == image_id)
              .order_by(Annotation.id).all())
    return [{"x": r.x, "y": r.y, "w": r.w, "h": r.h,
             "label": r.label, "confidence": r.confidence,
             "frozen": bool(r.is_frozen)} for r in rows]


def _autolabel_image_with_model(db, img, model, project, conf=None):
    """
    V7.0.0: использует класс проекта. Кидает 422, если модель
    не знает такого класса.
    """
    target_label = (project.object_class or DEFAULT_OBJECT_CLASS)
    target_ids = _resolve_target_class_ids(model, target_label)
    if not target_ids:
        raise HTTPException(
            422,
            f"Класс «{target_label}» не поддерживается активной моделью. "
            f"Выбери другую модель в настройках или обучи свою."
        )
    anns = _autolabel_image_predict(
        img.path, model, img.width, img.height, target_ids, target_label, conf
    )
    _save_autolabel(db, img.id, anns, target_label)
    return _load_annotations(db, img.id)


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
    """
    V7.0.0: имя класса в data.yaml берётся из project.object_class.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    object_class = (project.object_class if project else DEFAULT_OBJECT_CLASS) or DEFAULT_OBJECT_CLASS
    # YAML-safe: экранируем одинарные кавычки
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
    import select
    try:
        fileno = proc.stdout.fileno()
    except Exception:
        log.exception("cannot get stream fileno")
        return

    deadline_silence = time.time() + idle_timeout
    leftover = b""
    try:
        while True:
            if proc.poll() is not None:
                try:
                    rlist, _, _ = select.select([fileno], [], [], 0.1)
                except Exception:
                    break
                if not rlist:
                    break
            try:
                rlist, _, _ = select.select([fileno], [], [], 0.2)
            except Exception:
                break
            if not rlist:
                if proc.poll() is not None and time.time() > deadline_silence:
                    break
                continue
            chunk = os.read(fileno, 8192)
            if not chunk:
                break
            deadline_silence = time.time() + idle_timeout
            data = leftover + chunk
            lines = data.split(b'\n')
            leftover = lines.pop()
            for raw in lines:
                raw = raw.rstrip(b'\r')
                text = raw.decode('utf-8', errors='replace')
                line = _ANSI_RE.sub('', text).strip()
                if line:
                    on_line(line)
        if leftover:
            text = leftover.decode('utf-8', errors='replace')
            line = _ANSI_RE.sub('', text).strip()
            if line:
                on_line(line)
    except Exception:
        log.exception("read stream error")


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
        )
        with TRAIN_LOCK:
            TRAIN_PROCESS = proc
        _read_stream_and_parse(proc, _handle_train_line)
        ret = proc.wait()
        with TRAIN_LOCK:
            status = TRAIN_STATE["status"]
        if status == "stopping":
            with TRAIN_LOCK:
                TRAIN_STATE["status"] = "stopped"
                TRAIN_STATE["message"] = "Обучение остановлено пользователем"
            log_status("warning", "train", "Обучение остановлено пользователем")
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
                except Exception:
                    log.exception("activate trained model %s failed", new_name)
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
}
BATCH_LOCK = threading.Lock()
BATCH_STOP = threading.Event()
BATCH_THREAD = None
BATCH_EVENT = threading.Event()


def _batch_snapshot():
    with BATCH_LOCK:
        return dict(BATCH_STATE)


def _batch_worker(image_ids, model_path, project_id):
    """
    V7.0.0: использует класс проекта. Если модель не поддерживает класс —
    завершается со статусом error.
    """
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
        log_status("info", "autolabel",
                   f"Батч-авторазметка: {total} изображений, класс «{target_label}»")
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
                anns = _autolabel_image_predict(
                    img.path, model, img.width, img.height, target_ids, target_label
                )
                _save_autolabel_no_commit(db, iid, anns, target_label)
                pending_since_commit += 1
                with BATCH_LOCK:
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
# FastAPI app + lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        n = cleanup_expired_trash(db)
        if n:
            log.info("Удалено устаревших объектов из корзины: %d", n)
    finally:
        db.close()
    _start_trash_cleaner_thread()
    t = threading.Thread(target=_bootstrap_default_model_if_empty,
                         daemon=True, name="model-bootstrap")
    t.start()
    log_status("info", "system", f"Dataset Builder {APP_VERSION} запущен")
    yield
    log_status("info", "system", "Приложение останавливается")


# V7.0.0: приложение переименовано
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
            if path.endswith("/import"):
                limit = MAX_IMPORT_BYTES
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
    return (html
            .replace("__VERSION__", APP_VERSION)
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
    # V7.0.0: считаем аннотации по проекту
    ann_counts = dict(
        db.query(ImageModel.project_id, func.count(Annotation.id))
          .join(Annotation, Annotation.image_id == ImageModel.id)
          .filter(ImageModel.is_deleted.is_(False))
          .group_by(ImageModel.project_id).all()
    )
    return [{
        "id": p.id,
        "name": p.name,
        "images_count": int(counts.get(p.id, 0)),
        "annotations_count": int(ann_counts.get(p.id, 0)),  # V7.0.0
        "object_class": p.object_class or DEFAULT_OBJECT_CLASS,       # V7.0.0
        "object_class_source": p.object_class_source or "list",       # V7.0.0
    } for p in rows]


@app.post("/api/projects")
def create_project(
    name: str = Form(...),
    object_class: str = Form(DEFAULT_OBJECT_CLASS),          # V7.0.0
    object_class_source: str = Form("list"),                 # V7.0.0
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name:
        raise HTTPException(400, "Пустое имя проекта")
    if len(name) > 255:
        raise HTTPException(400, "Слишком длинное имя")

    # V7.0.0
    cls = _validate_object_class(object_class)
    src = _validate_object_class_source(object_class_source)

    p = Project(
        name=name,
        created_at=utcnow(),
        is_deleted=False,
        object_class=cls,
        object_class_source=src,
    )
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
        raise HTTPException(404, "Project not found")
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
        raise HTTPException(404, "Project not found")
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
        raise HTTPException(404, "Project not found")
    name = proj.name
    _purge_projects(db, [project_id])
    log_status("warning", "project", f"Проект «{name}» удалён навсегда")
    return {"status": "ok", "deleted_id": project_id, "permanent": True}


# ---------------------------------------------------------------------------
# V7.0.0: информация о проекте + настройки + очистка разметки
# ---------------------------------------------------------------------------
@app.get("/api/projects/{project_id}/info")
def project_info(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project not found")

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
        "id": proj.id,
        "name": proj.name,
        "object_class": proj.object_class or DEFAULT_OBJECT_CLASS,
        "object_class_source": proj.object_class_source or "list",
        "images_count": int(images_count),
        "annotations_count": int(ann_count),
        "is_deleted": bool(proj.is_deleted),
    }


@app.patch("/api/projects/{project_id}/settings")
def update_project_settings(
    project_id: int,
    payload: ProjectSettingsIn,
    db: Session = Depends(get_db),
):
    """
    V7.0.0: меняет object_class у проекта.
    Запрещено, если в проекте есть хоть одна активная аннотация.
    """
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project not found")

    new_class = _validate_object_class(payload.object_class)
    new_src = _validate_object_class_source(payload.object_class_source)

    # Считаем аннотации в проекте (только для активных изображений)
    ann_count = (db.query(func.count(Annotation.id))
                   .join(ImageModel, Annotation.image_id == ImageModel.id)
                   .filter(ImageModel.project_id == project_id,
                           ImageModel.is_deleted.is_(False))
                   .scalar() or 0)

    cls_changed = (proj.object_class or DEFAULT_OBJECT_CLASS) != new_class \
        or (proj.object_class_source or "list") != new_src

    if cls_changed and ann_count > 0:
        raise HTTPException(
            409,
            f"В проекте уже размечено {ann_count} рамок. "
            f"Сначала очистите разметку, потом меняйте класс."
        )

    proj.object_class = new_class
    proj.object_class_source = new_src
    db.commit()

    log_status("info", "project",
               f"Проект «{proj.name}»: класс изменён на «{new_class}»")
    return {
        "id": proj.id,
        "object_class": proj.object_class,
        "object_class_source": proj.object_class_source,
    }


@app.post("/api/projects/{project_id}/clear_annotations")
def clear_project_annotations(project_id: int, db: Session = Depends(get_db)):
    """
    V7.0.0: удаляет все аннотации во всех активных изображениях проекта.
    """
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project not found")

    img_ids_q = (db.query(ImageModel.id)
                   .filter(ImageModel.project_id == project_id,
                           ImageModel.is_deleted.is_(False)))
    img_ids = [iid for (iid,) in img_ids_q.all()]

    if not img_ids:
        return {"status": "ok", "cleared": 0}

    # Считаем перед удалением
    total = (db.query(func.count(Annotation.id))
               .filter(Annotation.image_id.in_(img_ids))
               .scalar() or 0)

    db.query(Annotation).filter(Annotation.image_id.in_(img_ids)) \
        .delete(synchronize_session=False)
    db.commit()

    log_status("warning", "project",
               f"Проект «{proj.name}»: очищено рамок {total}")
    return {"status": "ok", "cleared": int(total)}


# ВАЖНО: объявлено до /api/projects/{project_id} во избежание конфликта
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
            ImageModel.project_id == r.id
        ).scalar() or 0
        days_left = None
        if r.deleted_at and ttl > 0:
            days_left = max(0, (r.deleted_at + timedelta(days=ttl) - now).days)
        out.append({
            "id": r.id, "name": r.name,
            "images_count": int(cnt),
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
# V7.0.0: классы объектов активной модели
# ---------------------------------------------------------------------------
@app.get("/api/object_classes")
def object_classes(db: Session = Depends(get_db)):
    """
    Возвращает список классов из активной модели + source.
    source: 'model' — из загруженной модели, 'empty' — модель не загружена.
    """
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


@app.post("/api/models/activate")
def activate_model(name: str = Form(...), db: Session = Depends(get_db)):
    with _MODEL_ACTIVATION_LOCK:
        p = _safe_model_path(name)
        if not os.path.exists(p):
            raise HTTPException(404, "Модель не найдена")
        set_setting(db, SETTING_ACTIVE_MODEL, name)
        _clear_yolo_cache()
    log_status("info", "model", f"Активная модель: {name}")
    return {"active": name}


@app.delete("/api/models/{name}")
def delete_model(name: str, db: Session = Depends(get_db)):
    p = _safe_model_path(name)
    if not os.path.exists(p):
        raise HTTPException(404, "Модель не найдена")
    if os.path.islink(p):
        raise HTTPException(400, "Символические ссылки не удаляются")

    active = get_setting(db, SETTING_ACTIVE_MODEL, "")
    if active == name:
        raise HTTPException(400, "Это активная модель. Сначала переключись на другую.")

    pt_files = [f for f in os.listdir(MODEL_DIR) if f.endswith(".pt")]
    if len(pt_files) <= 1:
        raise HTTPException(400, "Это последняя модель в папке. Нужна хотя бы одна для авторазметки.")

    try:
        os.remove(p)
    except OSError as e:
        raise HTTPException(500, f"Не удалось удалить: {e}")

    with _YOLO_CACHE_LOCK:
        _YOLO_CACHE.pop(p, None)

    log_status("warning", "model", f"Модель удалена: {name}")
    return {"status": "ok"}


@app.post("/api/models/{name}/rename")
def rename_model(name: str, new_name: str = Form(...), db: Session = Depends(get_db)):
    old_path = _safe_model_path(name)
    if not os.path.exists(old_path):
        raise HTTPException(404, "Модель не найдена")

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
# Обучение (endpoints)
# ---------------------------------------------------------------------------
@app.post("/api/train/start")
def train_start(project_id: int = Form(...), base_model: str = Form("yolov8n.pt"),
                pretrain_dataset: str = Form("oiv7"),
                model_name: str = Form(""),
                epochs: int = Form(50), imgsz: int = Form(640),
                freeze: int = Form(8), lr0: float = Form(0.001),
                db: Session = Depends(get_db)):
    _rate_limit(_limiter_train, "local", "Слишком часто запускается обучение")

    with TRAIN_LOCK:
        if TRAIN_STATE["status"] in ("running", "stopping", "preparing"):
            raise HTTPException(409, "Обучение уже идёт")
        TRAIN_STATE["status"] = "preparing"
    try:
        proj = db.query(Project).filter(Project.id == project_id,
                                         Project.is_deleted.is_(False)).first()
        if not proj:
            raise HTTPException(404, "Project not found")
        epochs = max(1, min(MAX_EPOCHS, int(epochs)))
        imgsz = max(64, min(2048, int(imgsz)))

        custom_name = ""
        if model_name and model_name.strip():
            custom_name = _sanitize_model_name(model_name)
            if not custom_name:
                raise HTTPException(400, "Некорректное имя модели")

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
        TRAIN_STATE["message"] = "Останавливаю..."
        proc = TRAIN_PROCESS
    TRAIN_EVENT.set()
    if proc is not None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            log.exception("stop training failed")
    log_status("warning", "train", "Запрошена остановка обучения")
    return {"status": "stopping"}


@app.get("/api/train/events")
async def train_events():
    async def gen():
        snap = _train_snapshot()
        yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
        last = json.dumps(snap, ensure_ascii=False)
        while True:
            await asyncio.get_event_loop().run_in_executor(None, TRAIN_EVENT.wait, 1.0)
            TRAIN_EVENT.clear()
            snap = _train_snapshot()
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
            raise HTTPException(409, "Нельзя сбросить, пока идёт обучение")
    _train_reset()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Батч-авторазметка (endpoints)
# ---------------------------------------------------------------------------
@app.post("/api/autolabel/batch/start")
def batch_autolabel_start(payload: BatchAutolabelIn, db: Session = Depends(get_db)):
    global BATCH_THREAD
    _rate_limit(_limiter_autolabel, "local", "Слишком много запусков батча")

    with BATCH_LOCK:
        if BATCH_STATE["status"] == "running":
            raise HTTPException(409, "Батч уже идёт")
        ids = [int(x) for x in (payload.image_ids or [])]
        if not ids:
            raise HTTPException(400, "Пустой список image_ids")
        BATCH_STATE["status"] = "starting"
    model_path = get_active_model_path(db)
    if not model_path:
        with BATCH_LOCK:
            BATCH_STATE["status"] = "idle"
        raise HTTPException(501, "Активная модель не найдена")

    # V7.0.0: проверяем, что класс проекта поддерживается моделью
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
        })
    BATCH_EVENT.set()
    t = threading.Thread(target=_batch_worker,
                         args=(ids, model_path, payload.project_id), daemon=True)
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
# Похожие / копирование / теги
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
        d = hamming_hex(target, r.phash)
        if d <= threshold:
            items.append({"id": r.id, "filename": r.filename, "distance": d})

    if len(items) < limit:
        rest = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
                  .filter(ImageModel.project_id == project_id,
                          ImageModel.is_deleted.is_(False),
                          ImageModel.id != image_id,
                          ImageModel.phash.isnot(None),
                          ~ImageModel.phash.like(f"{prefix}%"))
                  .limit(2000).all())
        for r in rest:
            d = hamming_hex(target, r.phash)
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
        raise HTTPException(404, "Image not found")
    if target.project_id != source.project_id:
        raise HTTPException(400, "Изображения из разных проектов")
    src_anns = db.query(Annotation).filter(Annotation.image_id == source_id).all()
    db.query(Annotation).filter(Annotation.image_id == target_id).delete()
    for a in src_anns:
        db.add(Annotation(image_id=target_id, x=a.x, y=a.y, w=a.w, h=a.h,
                          label=a.label, confidence=None, is_frozen=False))
    db.commit()
    return {"status": "ok", "count": len(src_anns)}


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
        raise HTTPException(404, "Project not found")
    name = name.strip()
    if not name:
        raise HTTPException(400, "Пустое имя тега")
    if len(name) > 64:
        raise HTTPException(400, "Слишком длинное имя")

    color_clean = (color or "").strip()
    if not _HEX_COLOR_RE.match(color_clean):
        raise HTTPException(400, f"Некорректный цвет: {color!r} (ожидается #RRGGBB)")

    existing = db.query(Tag).filter(Tag.project_id == project_id, Tag.name == name).first()
    if existing:
        raise HTTPException(409, "Такой тег уже существует")

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
            raise HTTPException(400, "Пустое имя")
        dup = db.query(Tag).filter(Tag.project_id == t.project_id,
                                     Tag.name == nm, Tag.id != t.id).first()
        if dup:
            raise HTTPException(409, "Такой тег уже существует")
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
def set_image_tags(image_id: int, tag_ids: list[int] = Body(...),
                   db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
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
    return {
        "status": "ok",
        "updated": len(imgs),
        "added": len(valid_add),
        "removed": len(valid_remove),
    }


# ---------------------------------------------------------------------------
# Изображения
# ---------------------------------------------------------------------------
@app.post("/api/projects/{project_id}/images")
def upload_image(project_id: int, file: UploadFile = File(...),
                 db: Session = Depends(get_db)):
    _rate_limit(_limiter_upload, "local", "Слишком много загрузок. Подожди минуту.")

    proj = db.query(Project).filter(Project.id == project_id,
                                     Project.is_deleted.is_(False)).first()
    if not proj:
        raise HTTPException(404, "Project not found")

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
    im = ImageModel(
        project_id=project_id, filename=unique_name,
        path=path, width=FIXED_SIZE[0], height=FIXED_SIZE[1],
        is_deleted=False, deleted_at=None, phash=ph or None, is_hard=False,
    )
    db.add(im)
    db.commit()
    db.refresh(im)
    ensure_thumb(im.id, im.path)
    return {"id": im.id, "filename": im.filename,
            "width": im.width, "height": im.height,
            "annotation_count": 0, "is_deleted": False, "is_hard": False,
            "renamed_from": original_name if unique_name != original_name else None}


@app.post("/api/images/{image_id}/rename")
def rename_image(image_id: int, filename: str = Form(...), db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
    raw = (filename or "").strip()
    validate_user_filename(raw)
    _, old_ext = _split_name_ext(img.filename)
    new_base, _ = _split_name_ext(raw)
    new_base = new_base.strip().rstrip('.')
    if not new_base:
        raise HTTPException(400, "Пустое имя файла (без расширения)")
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
        raise HTTPException(404, "Image not found")
    img.is_hard = not bool(img.is_hard)
    db.commit()
    return {"id": img.id, "is_hard": bool(img.is_hard)}


@app.get("/api/images/{image_id}/thumb")
def get_image_thumb(image_id: int, db: Session = Depends(get_db)):
    row = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not row:
        raise HTTPException(404, "Image not found")
    p = ensure_thumb(row.id, row.path)
    if not p or not os.path.exists(p):
        raise HTTPException(500, "Cannot generate thumbnail")
    return FileResponse(p, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/projects/{project_id}/images")
def list_images(project_id: int,
                offset: int = 0,
                limit: int = 0,
                db: Session = Depends(get_db)):
    q = (db.query(ImageModel)
           .filter(ImageModel.project_id == project_id,
                   ImageModel.is_deleted.is_(False))
           .order_by(ImageModel.id))

    total = q.count()

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
    } for r in rows]

    if limit == 0:
        return items
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@app.get("/api/projects/{project_id}/trash")
def list_trash(project_id: int, db: Session = Depends(get_db)):
    rows = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(True))
              .order_by(ImageModel.deleted_at.desc(), ImageModel.id.desc()).all())
    ttl = get_trash_ttl_days(db)
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


@app.get("/api/projects/{project_id}/stats")
def project_stats(project_id: int, db: Session = Depends(get_db)):
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

    per_rows = (db.query(Annotation.image_id,
                          func.count(Annotation.id),
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
        "total_images": total,
        "annotated_images": annotated,
        "unannotated_images": total - annotated,
        "total_boxes": total_boxes,
        "avg_boxes": (total_boxes / annotated) if annotated else 0.0,
        "confidence": {"manual": manual, "low": low, "mid": mid, "high": high},
        "top_suspicious": top_suspicious,
        "unannotated_sample": unannotated_sample,
    }


@app.get("/api/projects/{project_id}/stats.csv")
def export_stats_csv(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project not found")
    imgs = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False))
              .order_by(ImageModel.id).all())
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
        raise HTTPException(404, "Image not found")
    return FileResponse(row.path)


@app.delete("/api/images/{image_id}")
def soft_delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
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
        raise HTTPException(404, "Image not found")
    file_path = img.path
    db.delete(img)
    db.commit()
    _remove_file_safe(file_path)
    _remove_thumb(image_id)
    return {"status": "ok", "deleted_id": image_id, "permanent": True}


@app.post("/api/images/batch_delete")
def batch_delete_images(ids: list[int] = Body(...), db: Session = Depends(get_db)):
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
def batch_restore_images(ids: list[int] = Body(...), db: Session = Depends(get_db)):
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
def batch_permanent_delete_images(ids: list[int] = Body(...), db: Session = Depends(get_db)):
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
        raise HTTPException(404, "Image not found")
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
        raise HTTPException(404, "Image not found")
    rows = db.query(Annotation).filter(Annotation.image_id == image_id).all()
    return [{"x": a.x, "y": a.y, "w": a.w, "h": a.h,
             "label": a.label, "confidence": a.confidence,
             "frozen": bool(a.is_frozen)} for a in rows]


@app.post("/api/images/{image_id}/annotations")
def save_annotations(image_id: int, annotations: list[AnnotationIn],
                     db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
    db.query(Annotation).filter(Annotation.image_id == image_id).delete()
    for a in annotations:
        db.add(Annotation(image_id=image_id, x=a.x, y=a.y, w=a.w, h=a.h,
                          label=a.label, confidence=a.confidence,
                          is_frozen=bool(a.frozen)))
    db.commit()
    return {"status": "ok", "count": len(annotations)}


@app.post("/api/images/{image_id}/autolabel")
def autolabel(image_id: int, db: Session = Depends(get_db)):
    _rate_limit(_limiter_autolabel, "local", "Слишком много авторазметок. Подожди минуту.")

    model_path = get_active_model_path(db)
    if not model_path:
        raise HTTPException(501, "Активная модель не найдена")
    try:
        model = _get_yolo_model(model_path)
    except ImportError:
        raise HTTPException(501, "ultralytics не установлен")
    except Exception as e:
        raise HTTPException(500, f"Ошибка загрузки модели: {_safe_error_message(e)}")
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
    project = db.query(Project).filter(Project.id == img.project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    # V7.0.0: класс берётся из проекта
    return _autolabel_image_with_model(db, img, model, project)


# ---------------------------------------------------------------------------
# Импорт датасета
# ---------------------------------------------------------------------------
@app.post("/api/projects/{project_id}/import")
def import_annotations(project_id: int, file: UploadFile = File(...),
                       db: Session = Depends(get_db)):
    _rate_limit(_limiter_import, "local", "Слишком много импортов. Подожди 10 минут.")

    proj = db.query(Project).filter(Project.id == project_id,
                                     Project.is_deleted.is_(False)).first()
    if not proj:
        raise HTTPException(404, "Project not found")

    # V7.0.0: класс проекта используется как default_label для парсеров
    project_class = proj.object_class or DEFAULT_OBJECT_CLASS

    content_length = file.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_IMPORT_BYTES:
                raise HTTPException(413, f"Архив больше {MAX_IMPORT_MB} МБ")
        except (ValueError, TypeError):
            pass

    tmp_dir = tempfile.mkdtemp(prefix="pdb_import_", dir=IMPORT_DIR)
    tmp_zip = os.path.join(tmp_dir, "_upload.zip")
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

        try:
            with zipfile.ZipFile(tmp_zip) as z:
                _safe_extract_zip(z, tmp_dir)
        except zipfile.BadZipFile:
            raise HTTPException(400, "Файл не является zip-архивом")
        except HTTPException:
            raise
        except Exception as e:
            log.exception("zip extract failed")
            raise HTTPException(400, f"Ошибка распаковки: {e}")
        finally:
            try:
                os.remove(tmp_zip)
            except OSError:
                pass

        fmt, src = detect_format(tmp_dir)
        image_files_peek = _collect_image_files(tmp_dir)

        if not fmt and not image_files_peek:
            raise HTTPException(400, "Архив пуст или не содержит изображений/разметки")

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
                phash_buckets[r.phash[:4]].append((r.id, r.filename, r.phash))

        def _find_dup_mem(ph):
            if not ph or len(ph) < 4:
                return None
            target_b = ph[:4]
            for (_rid, _fn, p) in phash_buckets.get(target_b, []):
                if hamming_hex(ph, p) <= PHASH_DUPLICATE_THRESHOLD:
                    return (_rid, _fn, p)
            for b in list(phash_buckets.keys()):
                if b == target_b:
                    continue
                for (_rid, _fn, p) in phash_buckets[b]:
                    if hamming_hex(ph, p) <= PHASH_DUPLICATE_THRESHOLD:
                        return (_rid, _fn, p)
            return None

        imported_images = 0
        skipped_duplicates = 0
        failed_images = 0
        image_files = image_files_peek

        pending = []

        def _flush_pending():
            nonlocal pending
            if not pending:
                return
            db.flush()
            for (im_x, path_x, stem_x) in pending:
                try:
                    ensure_thumb(im_x.id, path_x)
                except Exception:
                    log.warning("thumb fail for %s", im_x.id)
                by_stem[stem_x] = im_x
            pending = []

        for img_path in image_files:
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
            im = ImageModel(
                project_id=project_id, filename=unique_name,
                path=new_path, width=FIXED_SIZE[0], height=FIXED_SIZE[1],
                is_deleted=False, deleted_at=None, phash=ph or None, is_hard=False,
            )
            db.add(im)
            if ph and len(ph) >= 4:
                phash_buckets[ph[:4]].append((None, unique_name, ph))
            pending.append((im, new_path, stem_l))
            imported_images += 1

            if len(pending) >= BATCH_IMPORT_CHUNK:
                _flush_pending()

        _flush_pending()
        db.commit()

        # V7.0.0: парсеры получают default_label = класс проекта
        parsed = {}
        if fmt == "coco":
            parsed = parse_coco(src, default_label=project_class)
        elif fmt == "yolo":
            parsed = parse_yolo(tmp_dir, default_label=project_class)
        elif fmt == "cvat":
            parsed = parse_cvat(src, default_label=project_class)
        elif fmt == "ls":
            parsed = parse_label_studio(src, default_label=project_class)
        elif fmt == "images_only":
            parsed = {}

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
                    # V7.0.0: всегда класс проекта, даже если в файле другой
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
                   f"картинок +{imported_images}, пропущено дубл. {skipped_duplicates}, "
                   f"привязано {matched}, рамок {added_anns}, "
                   f"не найдено {len(unmatched)}")
        return {"status": "ok", "format": fmt,
                "imported_images": imported_images,
                "skipped_duplicates": skipped_duplicates,
                "failed_images": failed_images,
                "matched_images": matched,
                "added_annotations": added_anns,
                "unmatched": unmatched[:50],
                "unmatched_count": len(unmatched)}
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Бэкап + скачивание
# ---------------------------------------------------------------------------
@app.post("/api/projects/{project_id}/backup")
def backup_project(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project not found")

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
        "app_version": APP_VERSION,
        "backup_version": 1,
        "is_backup": True,
        "created_at": utcnow().isoformat(),
        "project_id": proj.id,
        "project_name": proj.name,
        "project_created_at": proj.created_at.isoformat() if proj.created_at else None,
        # V7.0.0
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
        "status": "ok",
        "filename": zip_name,
        "path": zip_path,
        "size": size,
        "images_count": len(images),
        "tags_count": len(tags_out),
        "annotations_count": meta["annotations_count"],
    }


@app.get("/api/projects/{project_id}/backup/download/{filename}")
def download_backup(project_id: int, filename: str, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project not found")

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
# Экспорт — V7.0.0: имя класса берётся из проекта
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
        raise HTTPException(404, "Project not found")
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
        raise HTTPException(404, "Project not found")
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
                    # V7.0.0: имя категории = класс проекта
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
# Version
# ---------------------------------------------------------------------------
@app.get("/api/version")
def api_version():
    return {"version": APP_VERSION, "author": AUTHOR}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")