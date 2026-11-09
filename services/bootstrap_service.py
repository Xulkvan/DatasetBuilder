"""Model bootstrap: download YOLO models from GitHub releases."""
import os
import time
import shutil
import threading
import urllib.request
import urllib.error
import logging
import json
from datetime import datetime
from config import (
    SETTING_ACTIVE_MODEL, MODEL_DIR,
    YOLO_URL_TEMPLATE, YOLO_RELEASE_TAG,
)

log = logging.getLogger("db")

BOOTSTRAP_STATE = {
    "status": "idle", "message": "", "progress": 0.0, "filename": "",
    "started_at": None, "finished_at": None,
}
BOOTSTRAP_LOCK = threading.Lock()
BOOTSTRAP_EVENT = threading.Event()
BOOTSTRAP_THREAD = None
_MODEL_ACTIVATION_LOCK = threading.Lock()

def utcnow():
    from logger import utcnow as _utcnow
    return _utcnow()


def _checksums_path() -> str:
    from config import MODEL_DIR as _MD
    return os.path.join(_MD, "checksums.json")


def _load_local_checksums() -> dict:
    p = _checksums_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_local_checksum(model_name: str, sha256: str) -> None:
    d = _load_local_checksums()
    if d.get(model_name) == sha256:
        return
    d[model_name] = sha256
    try:
        with open(_checksums_path(), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except OSError:
        log.exception("bootstrap: cannot save checksums.json")


def _verify_model_sha256(path: str, model_name: str) -> bool:
    """Сверка SHA256 с YOLO_MODEL_SHA256; первый download pin'ит хэш локально.

    Локальный pin (models/checksums.json) защищает от подмены CDN/MITM
    при повторных скачиваниях даже если YOLO_MODEL_SHA256 в config.py
    не заполнен. Первый download — best-effort (пользователь должен
    доверять источнику один раз), повторные — strict.
    """
    import hashlib as _hl
    from config import YOLO_MODEL_SHA256 as _SHA256
    expected = (_SHA256 or {}).get(model_name)
    _local = _load_local_checksums()
    if not expected:
        expected = _local.get(model_name)
    h = _hl.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        log.warning("bootstrap: cannot read %s for checksum", path)
        return False
    actual = h.hexdigest()
    if not expected:
        _save_local_checksum(model_name, actual)
        log.info("bootstrap: first download of %s — checksum pinned locally",
                 model_name)
        return True
    if actual != expected:
        log.error("bootstrap: SHA256 mismatch for %s: %s != %s",
                  model_name, actual, expected)
        return False
    return True

def _bootstrap_snapshot():
    with BOOTSTRAP_LOCK:
        return dict(BOOTSTRAP_STATE)

def _bootstrap_set(**kwargs):
    with BOOTSTRAP_LOCK:
        BOOTSTRAP_STATE.update(kwargs)
    BOOTSTRAP_EVENT.set()

def _yolo_filename(size, pretrain, family="v8", task="detect"):
    size = size if size in ("n", "s", "m", "l", "x") else "n"
    # [STAGE3:YOLO26-BOOTSTRAP]
    prefix = ("yolo11" if family == "v11"
              else ("yolo26" if family == "v26" else "yolov8"))
    if task == "pose":
        return f"{prefix}{size}-pose.pt"
    if family == "v11":
        return f"{prefix}{size}.pt"
    if pretrain == "oiv7":
        return f"{prefix}{size}-oiv7.pt"
    return f"{prefix}{size}.pt"

def _download_with_progress(url, dest, on_progress=None, retries=2, expected_min_mb=1, expected_max_mb=1024):
    tmp = dest + ".part"
    last_exc = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 DatasetBuilder"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                if total > 0:
                    min_b = expected_min_mb * 1024 * 1024
                    max_b = expected_max_mb * 1024 * 1024
                    if total < min_b: raise IOError(f"Content-Length {total} < {min_b}")
                    if total > max_b: raise IOError(f"Content-Length {total} > {max_b}")
                done = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(128 * 1024)
                        if not chunk: break
                        f.write(chunk)
                        done += len(chunk)
                        if on_progress:
                            if total > 0: on_progress(done / total * 100.0, done, total)
                            else: on_progress(None, done, 0)
            if total > 0 and done < total:
                raise IOError(f"Не докачано: {done} из {total} байт")
            if done < 512 * 1024:
                raise IOError(f"Файл слишком мал: {done}")
            with open(tmp, "rb") as f:
                head = f.read(4)
            if head[:2] != b'PK':
                raise IOError("Файл не является PyTorch-моделью (.pt — zip)")
            os.replace(tmp, dest)
            return
        except Exception as e:
            last_exc = e
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except OSError: pass
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last_exc

def _download_model_worker(size, pretrain, custom_name, auto_activate, family="v8", task="detect"):
    global BOOTSTRAP_THREAD
    from services.settings_service import set_setting, get_setting
    from services.ml_service import _clear_yolo_cache, _invalidate_model_classes_cache
    from services.file_service import _sanitize_model_name, _unique_model_name_from_disk
    from database import SessionLocal
    try:
        fname = _yolo_filename(size, pretrain, family, task)
        url = YOLO_URL_TEMPLATE.format(tag=YOLO_RELEASE_TAG, name=fname)
        if custom_name:
            target_name = _sanitize_model_name(custom_name) or fname
        else:
            target_name = fname
        target_name = _unique_model_name_from_disk(target_name)
        target_path = os.path.join(MODEL_DIR, target_name)

        _bootstrap_set(status="downloading", message=f"Скачиваем {fname} …",
                       progress=0.0, filename=target_name,
                       started_at=utcnow().isoformat(), finished_at=None)

        def cb(pct, done, total):
            if pct is None:
                _bootstrap_set(message=f"Скачиваем {fname} … {done / (1024*1024):.1f} МБ", progress=0.0)
            else:
                _bootstrap_set(message=f"Скачиваем {fname} … {pct:.1f}%", progress=round(pct, 1))

        _download_with_progress(url, target_path, on_progress=cb)
        if not _verify_model_sha256(target_path, fname):
            try:
                os.remove(target_path)
            except OSError:
                pass
            raise IOError(f"SHA256 checksum mismatch for {fname}")

        activate = auto_activate
        if not activate:
            try:
                db2 = SessionLocal()
                try:
                    existing_active = get_setting(db2, SETTING_ACTIVE_MODEL, "")
                finally:
                    db2.close()
                if not existing_active:
                    activate = True
            except Exception:
                log.exception("check active model failed")

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

        _bootstrap_set(status="done", message=f"Модель загружена: {target_name}",
                       progress=100.0, filename=target_name,
                       finished_at=utcnow().isoformat())
    except Exception as e:
        log.exception("download error")
        _bootstrap_set(status="error", message=f"Не удалось скачать модель: {e}",
                       finished_at=utcnow().isoformat())
    finally:
        with BOOTSTRAP_LOCK:
            BOOTSTRAP_THREAD = None
        BOOTSTRAP_EVENT.set()

def _bootstrap_default_model_if_empty():
    try:
        existing = [f for f in os.listdir(MODEL_DIR) if f.endswith(".pt")]
        if existing: return
        log.warning("Моделей нет. Скачиваю yolov8n-oiv7.pt")
        _download_model_worker("n", "oiv7", "pig.pt", auto_activate=True, family="v8", task="detect")
    except Exception:
        log.exception("bootstrap error")
