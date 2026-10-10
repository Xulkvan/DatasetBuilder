"""
PigDatasetBuilder — V5.5
============================================================
Backend: FastAPI + MySQL + YOLO.
Frontend: index.html + style.css + app.js (лежат рядом, отдаются как статика).

Запуск:
    1) CREATE DATABASE pig_dataset CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    2) pip install -r requirements.txt
    3) python app.py
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
import random
import shutil
import zipfile
import tempfile
import threading
import subprocess
import asyncio
import logging
import urllib.request
import uvicorn

import xml.etree.ElementTree as ET

from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Depends, Body, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, Response, JSONResponse
from pydantic import BaseModel, Field, field_validator
from PIL import Image

Image.MAX_IMAGE_PIXELS = 100_000_000

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, ForeignKey,
    Boolean, DateTime, inspect, text, UniqueConstraint, Index, func, case
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pig")

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------
APP_VERSION = "V5.5"
AUTHOR = "Xulkvan"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
IMPORT_DIR = os.path.join(BASE_DIR, "imports")
MODEL_DIR = os.path.join(BASE_DIR, "models")
RUNS_DIR = os.path.join(BASE_DIR, "runs")
THUMB_DIR = os.path.join(BASE_DIR, "thumbs")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
MODEL_PATH = os.path.join(MODEL_DIR, "pig.pt")

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

INVALID_CHARS_RE = re.compile(r'[\\/:*?"<>|]')
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
_EPOCH_RE = re.compile(r'^\s*(\d+)/(\d+)\s+\d+(?:\.\d+)?G\s')
_MODEL_NAME_RE = re.compile(r'^[A-Za-z0-9_\-\.\(\) ]+\.pt$')
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"})
PIG_CLASS_NAMES = frozenset({"pig", "wild boar", "boar", "hog", "piglet", "swine"})

YOLO_RELEASE_TAG = "v8.3.0"
YOLO_URL_TEMPLATE = "https://github.com/ultralytics/assets/releases/download/{tag}/{name}"

MIN_BOX_AREA = 0.005
MAX_OVERLAP_IOU = 0.9
NESTED_RATIO = 0.9
MAX_ASPECT = 5.0
MAX_FREEZE_LAYERS = 9
BATCH_IMPORT_CHUNK = 100

for d in (UPLOAD_DIR, EXPORT_DIR, MODEL_DIR, IMPORT_DIR, RUNS_DIR, THUMB_DIR, BACKUP_DIR):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# In-memory status log
# ---------------------------------------------------------------------------
STATUS_LOG = deque(maxlen=1000)
STATUS_LOG_LOCK = threading.Lock()


def log_status(level: str, category: str, message: str, extra: Optional[dict] = None):
    entry = {
        "ts": utcnow().isoformat(timespec="seconds"),
        "level": (level or "info").lower(),
        "category": category,
        "message": str(message)[:800],
    }
    if extra:
        entry["extra"] = {k: str(v)[:200] for k, v in extra.items()}
    with STATUS_LOG_LOCK:
        STATUS_LOG.append(entry)
    lvl = {"error": log.error, "warning": log.warning}.get(entry["level"], log.info)
    lvl("[%s] %s", category, message)


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# ORM
# ---------------------------------------------------------------------------
class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=True)
    images = relationship("ImageModel", back_populates="project", cascade="all, delete-orphan")
    tags = relationship("Tag", back_populates="project", cascade="all, delete-orphan")


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
    image_id = Column(Integer, ForeignKey("images.id"), nullable=False, index=True)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    w = Column(Float, nullable=False)
    h = Column(Float, nullable=False)
    label = Column(String(64), nullable=False, default="pig")
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
    label: str = "pig"
    confidence: Optional[float] = None
    frozen: bool = False

    @field_validator('x', 'y', 'w', 'h')
    @classmethod
    def _clamp(cls, v):
        return max(0.0, min(1.0, float(v)))

    @field_validator('confidence')
    @classmethod
    def _conf_range(cls, v):
        if v is None:
            return None
        return max(0.0, min(1.0, float(v)))

    @field_validator('label')
    @classmethod
    def _label_len(cls, v):
        v = (v or "pig")[:64]
        return v or "pig"


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


# ---------------------------------------------------------------------------
# Миграция
# ---------------------------------------------------------------------------
def ensure_schema():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if "images" in tables:
        cols = {c["name"] for c in inspector.get_columns("images")}
        for col, ddl in [
            ("is_deleted", "TINYINT(1) NOT NULL DEFAULT 0"),
            ("deleted_at", "DATETIME NULL"),
            ("phash", "VARCHAR(16) NULL"),
            ("is_hard", "TINYINT(1) NOT NULL DEFAULT 0"),
        ]:
            if col not in cols:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE images ADD COLUMN {col} {ddl}"))
                log.info("migrate: images.%s added", col)

    if "annotations" in tables:
        cols = {c["name"] for c in inspector.get_columns("annotations")}
        if "confidence" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE annotations ADD COLUMN confidence FLOAT NULL"))
            log.info("migrate: annotations.confidence added")
        if "is_frozen" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE annotations ADD COLUMN is_frozen TINYINT(1) NOT NULL DEFAULT 0"))
            log.info("migrate: annotations.is_frozen added")

    if "projects" in tables:
        cols = {c["name"] for c in inspector.get_columns("projects")}
        if "created_at" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE projects ADD COLUMN created_at DATETIME NULL"))
            log.info("migrate: projects.created_at added")


ensure_schema()
Base.metadata.create_all(bind=engine)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
        return "#0071e3"
    return c.lower()


def _safe_model_path(name: str) -> str:
    if not name or not isinstance(name, str):
        raise HTTPException(400, "Некорректное имя модели")
    if ".." in name or "/" in name or "\\" in name:
        raise HTTPException(400, "Некорректный путь к модели")
    if not _MODEL_NAME_RE.match(name):
        raise HTTPException(400, "Некорректное имя модели")
    p = os.path.realpath(os.path.join(MODEL_DIR, name))
    root = os.path.realpath(MODEL_DIR)
    if not (p == root or p.startswith(root + os.sep)):
        raise HTTPException(400, "Некорректный путь к модели")
    return p


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
    if ".." in base or "/" in base or "\\" in base:
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
            pass
    if os.path.exists(MODEL_PATH):
        return MODEL_PATH
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
            return
        if os.path.isfile(real):
            os.remove(real)
    except OSError as e:
        log.warning("cannot remove %s: %s", p, e)


def cleanup_expired_trash(db) -> int:
    ttl = get_trash_ttl_days(db)
    if ttl <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=ttl)
    total = 0
    while True:
        rows = (db.query(ImageModel)
                  .filter(ImageModel.is_deleted == True,  # noqa: E712
                          ImageModel.deleted_at != None,   # noqa: E711
                          ImageModel.deleted_at < cutoff)
                  .limit(500).all())
        if not rows:
            break
        paths = [r.path for r in rows]
        ids = [r.id for r in rows]
        for r in rows:
            db.delete(r)
        db.flush()
        db.commit()
        for p in paths:
            _remove_file_safe(p)
        for iid in ids:
            _remove_thumb(iid)
        total += len(rows)
        if len(rows) < 500:
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
                        log.info("Корзина: удалено устаревших %d", n)
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


def _download_with_progress(url: str, dest: str, on_progress=None, retries: int = 2) -> None:
    tmp = dest + ".part"
    last_exc = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 PigDatasetBuilder"
            })
            with urllib.request.urlopen(req, timeout=90) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
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
                db2 = SessionLocal()
                try:
                    set_setting(db2, SETTING_ACTIVE_MODEL, target_name)
                    with _YOLO_CACHE_LOCK:
                        _YOLO_CACHE.clear()
                finally:
                    db2.close()
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


def _dct_cos_table(n):
    return [[math.cos((2 * x + 1) * u * math.pi / (2 * n)) for x in range(n)] for u in range(n)]


def _dct_cos_table_cached(n):
    t = _DCT_TABLE_CACHE.get(n)
    if t is None:
        t = _dct_cos_table(n)
        _DCT_TABLE_CACHE[n] = t
    return t


def phash_hex(image_path, hash_size=8, highfreq_factor=4) -> str:
    N = hash_size * highfreq_factor
    try:
        img = Image.open(image_path).convert("L").resize((N, N), Image.Resampling.LANCZOS)
    except Exception:
        return ""
    pixels = list(img.getdata())
    cos_t = _dct_cos_table_cached(N)
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


def _phash_bucket(phash: str, depth: int = 4) -> str:
    return (phash or "")[:depth]


def find_duplicate(db, project_id: int, phash: str):
    if not phash:
        return None
    rows = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted == False,     # noqa: E712
                      ImageModel.phash != None).all())    # noqa: E711
    if not rows:
        return None
    target_b = _phash_bucket(phash, 4)
    candidates = [r for r in rows if _phash_bucket(r.phash, 4) == target_b]
    for r in candidates:
        if hamming_hex(phash, r.phash) <= PHASH_DUPLICATE_THRESHOLD:
            return r
    if len(candidates) < len(rows):
        cand_ids = {r.id for r in candidates}
        for r in rows:
            if r.id in cand_ids:
                continue
            if hamming_hex(phash, r.phash) <= PHASH_DUPLICATE_THRESHOLD:
                return r
    return None


def _build_phash_buckets(db, project_id: int):
    rows = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted == False,    # noqa: E712
                      ImageModel.phash != None).all())   # noqa: E711
    buckets = defaultdict(list)
    for r in rows:
        if r.phash and len(r.phash) >= 4:
            buckets[r.phash[:4]].append((r.id, r.filename, r.phash))
    return buckets


def _find_duplicate_mem(buckets, phash: str):
    if not phash or len(phash) < 4:
        return None
    target_b = phash[:4]
    for (_rid, _fn, p) in buckets.get(target_b, []):
        if hamming_hex(phash, p) <= PHASH_DUPLICATE_THRESHOLD:
            return (_rid, _fn, p)
    for b in list(buckets.keys()):
        if b == target_b:
            continue
        for (_rid, _fn, p) in buckets[b]:
            if hamming_hex(phash, p) <= PHASH_DUPLICATE_THRESHOLD:
                return (_rid, _fn, p)
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
    return os.path.join(THUMB_DIR, f"{image_id}.jpg")


def _remove_thumb(image_id: int):
    _remove_file_safe(_thumb_path(image_id))


def ensure_thumb(image_id: int, src_path: str) -> str:
    p = _thumb_path(image_id)
    if os.path.exists(p):
        return p
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
        ImageModel.is_deleted == False,  # noqa: E712
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
    for ex in existing:
        e_base, e_ext = _split_name_ext(ex)
        if e_ext.lower() != ext.lower():
            continue
        if e_base == base_root:
            max_n = max(max_n, 0)
            continue
        m2 = re.match(r'^' + re.escape(base_root) + r' \((\d+)\)$', e_base)
        if m2:
            max_n = max(max_n, int(m2.group(1)))
    return f"{base_root} ({max_n + 1}){ext}"


def _is_image_ext(name: str) -> bool:
    _, ext = _split_name_ext(name)
    return ext.lower() in IMAGE_EXTS


# ---------------------------------------------------------------------------
# Импорт разметки (парсеры)
# ---------------------------------------------------------------------------
def _basename_no_ext(name: str) -> str:
    base = os.path.basename(name or "")
    stem, _ = _split_name_ext(base)
    return stem.lower()


def _xywh_pixels_to_norm(x, y, w, h, iw, ih):
    if iw <= 0 or ih <= 0:
        return None
    return {"x": x / iw, "y": y / ih, "w": w / iw, "h": h / ih}


def parse_coco(json_path: str):
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
        norm = _xywh_pixels_to_norm(x, y, w, h, img.get("width", 0), img.get("height", 0))
        if not norm:
            continue
        key = _basename_no_ext(img.get("file_name", ""))
        if not key:
            continue
        out[key].append({"x": norm["x"], "y": norm["y"], "w": norm["w"], "h": norm["h"],
                         "label": "pig", "confidence": ann.get("score")})
    return out


def parse_yolo(zip_dir: str):
    out = defaultdict(list)
    labels_dir = None
    for root, dirs, files in os.walk(zip_dir):
        if os.path.basename(root) == "labels":
            labels_dir = root
            break
    if not labels_dir:
        return out
    for fn in os.listdir(labels_dir):
        if not fn.lower().endswith(".txt"):
            continue
        stem = _basename_no_ext(fn)
        path = os.path.join(labels_dir, fn)
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 5:
                    continue
                try:
                    _cls = int(parts[0]); xc, yc, w, h = map(float, parts[1:5])
                except ValueError:
                    continue
                out[stem].append({"x": xc - w/2, "y": yc - h/2, "w": w, "h": h,
                                  "label": "pig", "confidence": None})
    return out


def parse_cvat(xml_path: str):
    out = defaultdict(list)
    try:
        tree = ET.parse(xml_path); root = tree.getroot()
    except ET.ParseError:
        return out
    for img in root.findall("image"):
        iw = float(img.get("width") or 0); ih = float(img.get("height") or 0)
        key = _basename_no_ext(img.get("name", ""))
        if not key or iw <= 0 or ih <= 0:
            continue
        for box in img.findall("box"):
            try:
                xtl = float(box.get("xtl")); ytl = float(box.get("ytl"))
                xbr = float(box.get("xbr")); ybr = float(box.get("ybr"))
            except (TypeError, ValueError):
                continue
            x, y = xtl, ytl
            w, h = xbr - xtl, ybr - ytl
            if w <= 0 or h <= 0:
                continue
            norm = _xywh_pixels_to_norm(x, y, w, h, iw, ih)
            if not norm:
                continue
            out[key].append({"x": norm["x"], "y": norm["y"], "w": norm["w"], "h": norm["h"],
                             "label": "pig", "confidence": None})
    return out


def parse_label_studio(json_path: str):
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
                    continue
                val = r.get("value", {})
                out[key].append({"x": val.get("x", 0) / 100, "y": val.get("y", 0) / 100,
                                 "w": val.get("width", 0) / 100, "h": val.get("height", 0) / 100,
                                 "label": "pig", "confidence": None})
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
# Авторазметка
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


def _autolabel_image_with_model(db, img, model, conf=None):
    if conf is None:
        conf = CONF_THRESHOLD
    results = model(img.path, conf=conf, verbose=False)
    W, H = img.width, img.height
    names = getattr(model, "names", {}) or {}
    raw = []
    for r in results:
        for box in r.boxes:
            try:
                cls_id = int(box.cls[0])
            except Exception:
                cls_id = 0
            cls_name = str(names.get(cls_id, "")).strip().lower()
            if cls_name and cls_name not in PIG_CLASS_NAMES:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            try:
                bconf = float(box.conf[0])
            except Exception:
                bconf = None
            raw.append({"x": x1/W, "y": y1/H, "w": (x2-x1)/W, "h": (y2-y1)/H,
                        "label": "pig", "confidence": bconf})
    anns = dedup_boxes(raw)
    db.query(Annotation).filter(
        Annotation.image_id == img.id,
        Annotation.is_frozen == False  # noqa: E712
    ).delete(synchronize_session=False)
    for a in anns:
        db.add(Annotation(image_id=img.id, x=a["x"], y=a["y"], w=a["w"], h=a["h"],
                          label=a["label"], confidence=a["confidence"], is_frozen=False))
    db.commit()
    rows = (db.query(Annotation)
              .filter(Annotation.image_id == img.id)
              .order_by(Annotation.id).all())
    return [{"x": r.x, "y": r.y, "w": r.w, "h": r.h,
             "label": r.label, "confidence": r.confidence,
             "frozen": bool(r.is_frozen)} for r in rows]


# ---------------------------------------------------------------------------
# Обучение (SSE)
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
    dataset_dir = os.path.join(run_dir, "dataset")
    images_dir = os.path.join(dataset_dir, "images")
    labels_dir = os.path.join(dataset_dir, "labels")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(labels_dir, exist_ok=True)

    all_imgs = (db.query(ImageModel)
                  .filter(ImageModel.project_id == project_id,
                          ImageModel.is_deleted == False).all())  # noqa: E712

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
                    f"names: ['pig']\n")
        else:
            log.warning("val-набор пуст, использую train как val")
            f.write(f"path: {dataset_dir}\n"
                    f"train: images/train\n"
                    f"val: images/train\n"
                    f"nc: 1\n"
                    f"names: ['pig']\n")

    log.info("датасет: %d train / %d val (всего размечено %d из %d)",
             len(train_pairs), len(val_pairs), len(pairs), len(all_imgs))
    return yaml_path


def _handle_train_line(line: str):
    with TRAIN_LOCK:
        TRAIN_STATE["log_lines"].append(line)
        if len(TRAIN_STATE["log_lines"]) > 300:
            TRAIN_STATE["log_lines"] = TRAIN_STATE["log_lines"][-300:]
        m = _EPOCH_RE.match(line)
        if m:
            try:
                cur = int(m.group(1)); total = int(m.group(2))
            except (ValueError, TypeError):
                cur, total = 0, 0
            if 0 < cur <= total <= 10000:
                TRAIN_STATE["current_epoch"] = cur
                TRAIN_STATE["total_epochs"] = total
                TRAIN_STATE["progress"] = round(cur / total * 100, 1)
    TRAIN_EVENT.set()


def _read_stream_and_parse(proc, on_line):
    try:
        stream = proc.stdout
        buf = ""
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            buf += chunk
            parts = buf.replace('\r', '\n').split('\n')
            buf = parts.pop()
            for raw_line in parts:
                line = _ANSI_RE.sub('', raw_line).strip()
                if line:
                    on_line(line)
        if buf:
            line = _ANSI_RE.sub('', buf).strip()
            if line:
                on_line(line)
    except Exception:
        log.exception("read stream error")


def _run_training_thread(args, run_dir, run_id, custom_name):
    global TRAIN_PROCESS
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, encoding='utf-8', errors='replace',
                                cwd=BASE_DIR)
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
                    db2 = SessionLocal()
                    try:
                        set_setting(db2, SETTING_ACTIVE_MODEL, new_name)
                        with _YOLO_CACHE_LOCK:
                            _YOLO_CACHE.clear()
                    finally:
                        db2.close()
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
# Батч-авторазметка (SSE)
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
    global BATCH_THREAD
    db = SessionLocal()
    try:
        try:
            model = _get_yolo_model(model_path)
        except Exception as e:
            with BATCH_LOCK:
                BATCH_STATE["status"] = "error"
                BATCH_STATE["message"] = f"Модель не загружена: {e}"
            log_status("error", "autolabel", f"Батч: модель не загружена: {e}")
            BATCH_EVENT.set()
            return
        total = len(image_ids)
        with BATCH_LOCK:
            BATCH_STATE["total"] = total
        log_status("info", "autolabel", f"Батч-авторазметка: {total} изображений")
        BATCH_EVENT.set()
        for iid in image_ids:
            if BATCH_STOP.is_set():
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
                _autolabel_image_with_model(db, img, model)
                with BATCH_LOCK:
                    BATCH_STATE["done"] += 1
            except Exception as e:
                log.warning("batch fail image %s: %s", iid, e)
                db.rollback()
                with BATCH_LOCK:
                    BATCH_STATE["done"] += 1
                    BATCH_STATE["failed"] += 1
            BATCH_EVENT.set()
        with BATCH_LOCK:
            BATCH_STATE["status"] = "done"
            BATCH_STATE["message"] = "Готово"
            BATCH_STATE["current_id"] = None
            BATCH_STATE["current_filename"] = ""
        log_status("success", "autolabel",
                   f"Батч-авторазметка завершена: {BATCH_STATE['done'] - BATCH_STATE['failed']} ok, {BATCH_STATE['failed']} ошибок")
    finally:
        db.close()
        with BATCH_LOCK:
            BATCH_STATE["finished_at"] = utcnow().isoformat()
            BATCH_THREAD = None
        BATCH_EVENT.set()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        n = cleanup_expired_trash(db)
        if n:
            log.info("Удалено устаревших записей из корзины: %d", n)
    finally:
        db.close()
    _start_trash_cleaner_thread()
    t = threading.Thread(target=_bootstrap_default_model_if_empty,
                         daemon=True, name="model-bootstrap")
    t.start()
    log_status("info", "system", f"PigDatasetBuilder {APP_VERSION} запущен")
    yield
    log_status("info", "system", "Приложение останавливается")


app = FastAPI(title=f"PigDatasetBuilder {APP_VERSION}", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    log_status("error", "system", f"{type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --- Статика: index.html, style.css, app.js ---
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


# --- Проекты ---
@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    rows = db.query(Project).order_by(Project.id).all()
    counts = dict(
        db.query(ImageModel.project_id, func.count(ImageModel.id))
          .filter(ImageModel.is_deleted == False)  # noqa: E712
          .group_by(ImageModel.project_id).all()
    )
    return [{"id": p.id, "name": p.name, "images_count": int(counts.get(p.id, 0))} for p in rows]


@app.post("/api/projects")
def create_project(name: str = Form(...), db: Session = Depends(get_db)):
    name = name.strip()
    if not name:
        raise HTTPException(400, "Пустое имя проекта")
    p = Project(name=name, created_at=utcnow())
    db.add(p)
    db.commit()
    db.refresh(p)
    log_status("success", "project", f"Создан проект «{name}» (id={p.id})")
    return {"id": p.id, "name": p.name, "images_count": 0}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project not found")
    proj_name = proj.name
    paths = [im.path for im in proj.images]
    ids = [im.id for im in proj.images]
    db.delete(proj)
    db.commit()
    for p in paths:
        _remove_file_safe(p)
    for iid in ids:
        _remove_thumb(iid)
    log_status("warning", "project", f"Удалён проект «{proj_name}» (id={project_id}), файлов: {len(paths)}")
    return {"status": "ok", "deleted_id": project_id, "files_removed": len(paths)}


# --- Логи ---
@app.get("/api/logs")
def get_logs(limit: int = 300, level: Optional[str] = None, category: Optional[str] = None):
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


# --- Настройки ---
@app.get("/api/settings/trash_ttl")
def get_trash_ttl(db: Session = Depends(get_db)):
    return {"days": get_trash_ttl_days(db)}


@app.post("/api/settings/trash_ttl")
def update_trash_ttl(days: int = Form(...), db: Session = Depends(get_db)):
    days = max(0, min(3650, int(days)))
    set_setting(db, SETTING_TRASH_TTL, days)
    log_status("info", "settings", f"Корзина: автоочистка через {days} дн.")
    return {"days": days}


# --- Модели ---
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
    p = _safe_model_path(name)
    if not os.path.exists(p):
        raise HTTPException(404, "Модель не найдена")
    set_setting(db, SETTING_ACTIVE_MODEL, name)
    with _YOLO_CACHE_LOCK:
        _YOLO_CACHE.clear()
    log_status("info", "model", f"Активная модель: {name}")
    return {"active": name}


@app.delete("/api/models/{name}")
def delete_model(name: str, db: Session = Depends(get_db)):
    p = _safe_model_path(name)
    if not os.path.exists(p):
        raise HTTPException(404, "Модель не найдена")
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


# --- Обучение ---
@app.post("/api/train/start")
def train_start(project_id: int = Form(...), base_model: str = Form("yolov8n.pt"),
                pretrain_dataset: str = Form("oiv7"),
                model_name: str = Form(""),
                epochs: int = Form(50), imgsz: int = Form(640),
                freeze: int = Form(8), lr0: float = Form(0.001),
                db: Session = Depends(get_db)):
    with TRAIN_LOCK:
        if TRAIN_STATE["status"] in ("running", "stopping", "preparing"):
            raise HTTPException(409, "Обучение уже идёт")
        TRAIN_STATE["status"] = "preparing"
    try:
        proj = db.query(Project).filter(Project.id == project_id).first()
        if not proj:
            raise HTTPException(404, "Project not found")
        epochs = max(1, min(500, int(epochs)))
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
                   f"Обучение запущено: project={project_id}, base={model_path}, epochs={epochs}, name={custom_name or 'auto'}")

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
                "from ultralytics import YOLO; "
                f"YOLO({model_path!r}).train(data={yaml_path!r}, epochs={epochs}, imgsz={imgsz}, "
                f"project={out_dir!r}, name='train', exist_ok=True, device='cpu', verbose=True, "
                f"freeze={freeze_layers}, lr0={lr0_val}, patience=20, cos_lr=True, warmup_epochs=3)"
            )
            args = [sys.executable, "-c", py_code]
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


# --- Батч-авторазметка ---
@app.post("/api/autolabel/batch/start")
def batch_autolabel_start(payload: BatchAutolabelIn, db: Session = Depends(get_db)):
    global BATCH_THREAD
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
    t = threading.Thread(target=_batch_worker, args=(ids, model_path, payload.project_id), daemon=True)
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


# --- Похожие / копирование / теги ---
@app.get("/api/projects/{project_id}/similar/{image_id}")
def similar_images(project_id: int, image_id: int,
                   threshold: int = SIMILAR_DEFAULT_THRESHOLD,
                   limit: int = 30, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id,
                                       ImageModel.project_id == project_id).first()
    if not img or not img.phash:
        return {"items": [], "threshold": threshold}
    rows = (db.query(ImageModel.id, ImageModel.filename, ImageModel.phash)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted == False,   # noqa: E712
                      ImageModel.id != image_id,
                      ImageModel.phash != None).all())  # noqa: E711
    items = []
    for r in rows:
        d = hamming_hex(img.phash, r.phash)
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
                  ImageModel.is_deleted == False)  # noqa: E712
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
    existing = db.query(Tag).filter(Tag.project_id == project_id, Tag.name == name).first()
    if existing:
        raise HTTPException(409, "Такой тег уже существует")
    t = Tag(project_id=project_id, name=name, color=_validate_color(color))
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
        dup = db.query(Tag).filter(Tag.project_id == t.project_id, Tag.name == nm, Tag.id != t.id).first()
        if dup:
            raise HTTPException(409, "Такой тег уже существует")
        t.name = nm
    if color is not None:
        t.color = _validate_color(color)
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
def set_image_tags(image_id: int, tag_ids: list[int] = Body(...), db: Session = Depends(get_db)):
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


# --- Изображения ---
@app.post("/api/projects/{project_id}/images")
def upload_image(project_id: int, file: UploadFile = File(...),
                 db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project not found")
    try:
        img = Image.open(file.file).convert("RGB")
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
                          ImageModel.is_deleted == False,       # noqa: E712
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
def list_images(project_id: int, db: Session = Depends(get_db)):
    rows = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted == False)  # noqa: E712
              .order_by(ImageModel.id).all())
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
    for it in db.query(ImageTag.image_id, ImageTag.tag_id).filter(ImageTag.image_id.in_(ids)).all():
        tag_map[it.image_id].append(it.tag_id)
    return [{
        "id": r.id, "filename": r.filename, "width": r.width, "height": r.height,
        "annotation_count": stats.get(r.id, {}).get("cnt", 0),
        "is_deleted": False, "is_hard": bool(r.is_hard),
        "min_confidence": stats.get(r.id, {}).get("min_conf"),
        "avg_confidence": stats.get(r.id, {}).get("avg_conf"),
        "low_conf_count": stats.get(r.id, {}).get("low_cnt", 0),
        "tag_ids": tag_map.get(r.id, []),
    } for r in rows]


@app.get("/api/projects/{project_id}/trash")
def list_trash(project_id: int, db: Session = Depends(get_db)):
    rows = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted == True)  # noqa: E712
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
                         ImageModel.is_deleted == False))  # noqa: E712
    total_ids = [r[0] for r in total_q.all()]
    if not total_ids:
        return {"total_images": 0, "annotated_images": 0, "unannotated_images": 0,
                "total_boxes": 0, "avg_boxes": 0.0,
                "confidence": {"manual": 0, "low": 0, "mid": 0, "high": 0},
                "top_suspicious": [], "unannotated_sample": []}
    agg = db.query(
        func.count(Annotation.id).label("cnt"),
        func.sum(case((Annotation.confidence.is_(None), 1), else_=0)).label("manual"),
        func.sum(case((Annotation.confidence < 0.5, 1), else_=0)).label("low"),
        func.sum(case((((Annotation.confidence >= 0.5) & (Annotation.confidence < 0.75)), 1), else_=0)).label("mid"),
        func.sum(case((Annotation.confidence >= 0.75, 1), else_=0)).label("high"),
    ).filter(Annotation.image_id.in_(total_ids)).one()
    total_boxes = int(agg.cnt or 0)
    manual = int(agg.manual or 0)
    low = int(agg.low or 0)
    mid = int(agg.mid or 0)
    high = int(agg.high or 0)
    per = dict(db.query(Annotation.image_id, func.count(Annotation.id))
                 .filter(Annotation.image_id.in_(total_ids))
                 .group_by(Annotation.image_id).all())
    min_conf_rows = dict(db.query(Annotation.image_id, func.min(Annotation.confidence))
                           .filter(Annotation.image_id.in_(total_ids))
                           .group_by(Annotation.image_id).all())
    annotated = len([i for i in total_ids if per.get(i, 0) > 0])
    metas = {im.id: im for im in db.query(ImageModel).filter(ImageModel.id.in_(total_ids)).all()}
    suspicious_pool = []
    unannotated_sample = []
    for iid in total_ids:
        c = per.get(iid, 0)
        if c == 0:
            if len(unannotated_sample) < 20:
                im = metas.get(iid)
                if im:
                    unannotated_sample.append({"id": im.id, "filename": im.filename})
            continue
        im = metas.get(iid)
        if not im:
            continue
        suspicious_pool.append({"id": im.id, "filename": im.filename,
                                "annotation_count": c,
                                "min_confidence": min_conf_rows.get(iid)})
    suspicious_pool.sort(key=lambda x: (x["min_confidence"] if x["min_confidence"] is not None else 1.0))
    return {"total_images": len(total_ids), "annotated_images": annotated,
            "unannotated_images": len(total_ids) - annotated, "total_boxes": total_boxes,
            "avg_boxes": (total_boxes / annotated) if annotated else 0.0,
            "confidence": {"manual": manual, "low": low, "mid": mid, "high": high},
            "top_suspicious": suspicious_pool[:10],
            "unannotated_sample": unannotated_sample}


@app.get("/api/projects/{project_id}/stats.csv")
def export_stats_csv(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project not found")
    imgs = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted == False)  # noqa: E712
              .order_by(ImageModel.id).all())
    ids = [r.id for r in imgs] or [0]
    stats_rows = db.query(
        Annotation.image_id, func.count(Annotation.id),
        func.min(Annotation.confidence), func.avg(Annotation.confidence),
        func.sum(case((Annotation.confidence < 0.5, 1), else_=0)),
    ).filter(Annotation.image_id.in_(ids)).group_by(Annotation.image_id).all()
    stats = {s[0]: s for s in stats_rows}
    tag_ids_by_image = defaultdict(list)
    for it in db.query(ImageTag.image_id, ImageTag.tag_id).filter(ImageTag.image_id.in_(ids)).all():
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


@app.get("/api/projects/{project_id}/validate")
def validate_project(project_id: int, deep: bool = True, db: Session = Depends(get_db)):
    imgs = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted == False).all())  # noqa: E712
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
        for i in range(len(boxes)):
            for j in range(i+1, len(boxes)):
                a, b = boxes[i], boxes[j]
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
    for r in rows:
        r.is_deleted = True
        r.deleted_at = now
    db.commit()
    return {"deleted": len(rows), "ids": [r.id for r in rows]}


@app.post("/api/images/batch_restore")
def batch_restore_images(ids: list[int] = Body(...), db: Session = Depends(get_db)):
    if not ids:
        return {"restored": 0, "renamed": 0}
    rows = db.query(ImageModel).filter(ImageModel.id.in_(ids)).all()
    by_project = defaultdict(set)
    pending = defaultdict(set)
    total_renamed = 0
    for r in rows:
        if not r.is_deleted:
            continue
        pid = r.project_id
        if pid not in by_project:
            used = {n for (n,) in db.query(ImageModel.filename).filter(
                ImageModel.project_id == pid,
                ImageModel.is_deleted == False,  # noqa: E712
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
                elif e_base == base_root:
                    max_n = max(max_n, 0)
            new_name = f"{base_root} ({max_n + 1}){ext}"
            total_renamed += 1
        pending[pid].add(new_name)
        r.filename = new_name
        r.is_deleted = False
        r.deleted_at = None
    db.commit()
    return {"restored": len(rows), "renamed": total_renamed, "ids": [r.id for r in rows]}


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
                      ImageModel.is_deleted == True).all())  # noqa: E712
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
    img.filename = make_unique_filename(db, img.project_id, img.filename, exclude_id=img.id)
    img.is_deleted = False
    img.deleted_at = None
    db.commit()
    return {"status": "ok", "restored_id": image_id, "filename": img.filename}


@app.get("/api/images/{image_id}/annotations")
def get_annotations(image_id: int, db: Session = Depends(get_db)):
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
    model_path = get_active_model_path(db)
    if not model_path:
        raise HTTPException(501, "Активная модель не найдена")
    try:
        model = _get_yolo_model(model_path)
    except ImportError:
        raise HTTPException(501, "ultralytics не установлен")
    except Exception as e:
        raise HTTPException(500, f"Ошибка загрузки модели: {e}")
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
    return _autolabel_image_with_model(db, img, model)


# ---------------------------------------------------------------------------
# Импорт датасета (batch-commit + in-memory pHash-бакеты)
# ---------------------------------------------------------------------------
@app.post("/api/projects/{project_id}/import")
def import_annotations(project_id: int, file: UploadFile = File(...),
                       db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project not found")

    tmp_dir = tempfile.mkdtemp(prefix="pdb_import_", dir=IMPORT_DIR)
    try:
        content = file.file.read()
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                for member in z.namelist():
                    target = os.path.realpath(os.path.join(tmp_dir, member))
                    if not target.startswith(os.path.realpath(tmp_dir) + os.sep) and target != os.path.realpath(tmp_dir):
                        raise HTTPException(400, "Опасный путь в архиве")
                z.extractall(tmp_dir)
        except zipfile.BadZipFile:
            raise HTTPException(400, "Файл не является zip-архивом")

        fmt, src = detect_format(tmp_dir)
        if not fmt:
            image_files_peek = _collect_image_files(tmp_dir)
            if not image_files_peek:
                raise HTTPException(400, "Не удалось определить формат (нет ни разметки, ни изображений)")
            fmt = "images_only"

        existing = (db.query(ImageModel)
                      .filter(ImageModel.project_id == project_id,
                              ImageModel.is_deleted == False).all())  # noqa: E712
        by_stem = {}
        for im in existing:
            stem, _ = _split_name_ext(im.filename)
            by_stem[stem.lower()] = im

        phash_buckets = _build_phash_buckets(db, project_id)

        imported_images = 0
        skipped_duplicates = 0
        failed_images = 0
        image_files = _collect_image_files(tmp_dir)

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
                dup = _find_duplicate_mem(phash_buckets, ph)
                if dup:
                    _remove_file_safe(new_path)
                    skipped_duplicates += 1
                    continue

            display_name = sanitize_display_name(original_name, fallback=new_fname)
            unique_name = make_unique_filename(db, project_id, display_name)
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

        parsed = {}
        if fmt == "coco":
            parsed = parse_coco(src)
        elif fmt == "yolo":
            parsed = parse_yolo(tmp_dir)
        elif fmt == "cvat":
            parsed = parse_cvat(src)
        elif fmt == "ls":
            parsed = parse_label_studio(src)
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
                    label=b.get("label", "pig"),
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
                   f"Импорт проекта #{project_id}: формат {fmt}, "
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
# Бэкап проекта
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
                        ImageModel.is_deleted == False).all())  # noqa: E712
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
        raise HTTPException(500, f"Бэкап не удался: {e}")

    size = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0
    log_status("success", "backup",
               f"Бэкап проекта «{proj.name}» (id={project_id}): "
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
    n_train = int(round(n * parts[0]))
    n_val = int(round(n * parts[1]))
    n_test = n - n_train - n_val
    if n_test < 0:
        n_val += n_test; n_test = 0
    if n_val < 0:
        n_train += n_val; n_val = 0
    if n_train < 0:
        n_train = 0
    return {"train": items[:n_train], "val": items[n_train:n_train+n_val],
            "test": items[n_train+n_val:n_train+n_val+n_test]}


def _iname_for_export(img, naming, used):
    if naming == "original":
        stem, _ = _split_name_ext(img.filename)
        stem = INVALID_CHARS_RE.sub('_', stem).strip().rstrip('.') or str(img.id)
        base = stem
        n = 1
        while stem in used:
            stem = f"{base} ({n})"; n += 1
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
    images = (db.query(ImageModel)
                .filter(ImageModel.project_id == project_id,
                        ImageModel.is_deleted == False).all())  # noqa: E712
    if not images:
        raise HTTPException(404, "No images")
    buckets = _split_images(images, split)
    use_split = split and split != "none" and (len(buckets["val"]) + len(buckets["test"])) > 0
    zip_path = os.path.join(EXPORT_DIR, f"yolo_project_{project_id}_{naming}_{split}.zip")
    used = set()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        if use_split:
            data_yaml = "path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnc: 1\nnames: ['pig']\n"
        else:
            data_yaml = "path: .\ntrain: images\nval: images\nnc: 1\nnames: ['pig']\n"
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
    log_status("info", "export", f"Экспорт YOLO проекта #{project_id}: {len(images)} фото")
    return FileResponse(zip_path, filename=f"yolo_project_{project_id}_{suffix}.zip",
                        media_type="application/zip")


@app.get("/api/projects/{project_id}/export/coco")
def export_coco(project_id: int, naming: str = "numbered", split: str = "none",
                db: Session = Depends(get_db)):
    if naming not in ("original", "numbered"):
        naming = "numbered"
    images = (db.query(ImageModel)
                .filter(ImageModel.project_id == project_id,
                        ImageModel.is_deleted == False).all())  # noqa: E712
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
            coco = {"images": [], "annotations": [], "categories": [{"id": 1, "name": "pig"}]}
            ann_id = 1
            for img in bucket_images:
                iname = _iname_for_export(img, naming, used)
                coco["images"].append({"id": img.id, "file_name": iname,
                                       "width": img.width, "height": img.height})
                anns = db.query(Annotation).filter(Annotation.image_id == img.id).all()
                for a in anns:
                    x = a.x * img.width; y = a.y * img.height
                    w = a.w * img.width; h = a.h * img.height
                    ann = {"id": ann_id, "image_id": img.id, "category_id": 1,
                           "bbox": [x, y, w, h], "area": w*h, "iscrowd": 0}
                    if a.confidence is not None:
                        ann["score"] = a.confidence
                    coco["annotations"].append(ann); ann_id += 1
                z.write(img.path, f"{sub}/{iname}")
            z.writestr(f"coco_{bucket_name}.json", json.dumps(coco, ensure_ascii=False, indent=2))
    suffix = "orig" if naming == "original" else "num"
    suffix += "_split" if use_split else ""
    _cleanup_old_exports("coco_project_")
    log_status("info", "export", f"Экспорт COCO проекта #{project_id}: {len(images)} фото")
    return FileResponse(zip_path, filename=f"coco_project_{project_id}_{suffix}.zip",
                        media_type="application/zip")


@app.get("/api/version")
def api_version():
    return {"version": APP_VERSION, "author": AUTHOR}