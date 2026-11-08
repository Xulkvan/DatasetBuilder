import logging
"""routers/models.py — [PATCH:STAGE6-F03-4.1] Models endpoints."""
import os
import threading
import datetime
import asyncio
import json
import subprocess
import sys
import uuid
from fastapi import APIRouter, HTTPException, Depends, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from config import MODEL_DIR, SETTING_ACTIVE_MODEL, SETTING_ACTIVE_POSE_MODEL
from services.file_service import (
    _safe_model_path, _sanitize_model_name, _unique_model_name_from_disk,
)
from services.settings_service import get_setting, set_setting
from services.ml_service import (
    _clear_yolo_cache, _invalidate_model_classes_cache,
    _is_pose_model_name, _is_single_model_mode, _get_model_classes_cached,
    _YOLO_CACHE,
)
from services.bootstrap_service import (
    BOOTSTRAP_STATE, BOOTSTRAP_LOCK, BOOTSTRAP_EVENT,
    _MODEL_ACTIVATION_LOCK, _bootstrap_snapshot, _download_model_worker,
)
from services import bootstrap_service as _bootstrap_svc
from services.errors import _safe_error_message
from logger import log_status, utcnow
from schemas import DownloadModelIn

log = logging.getLogger("db")

router = APIRouter()

@router.get("/api/models")
def list_models(db: Session = Depends(get_db)):
    result = []
    if os.path.isdir(MODEL_DIR):
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
                "created_at": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
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

@router.get("/api/models/compatibility")
def models_compatibility(object_class: str, db: Session = Depends(get_db)):
    obj = (object_class or "").strip().lower()
    if not obj:
        raise HTTPException(400, "object_class обязателен")
    names = []
    if os.path.isdir(MODEL_DIR):
        names = sorted([f for f in os.listdir(MODEL_DIR) if f.endswith((".pt", ".onnx"))])
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

@router.post("/api/models/activate")
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

@router.delete("/api/models/{name}")
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
    pt_files = [f for f in os.listdir(MODEL_DIR) if f.endswith((".pt", ".onnx"))]
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

@router.post("/api/models/{name}/reveal")
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

@router.post("/api/models/{name}/rename")
def rename_model(name: str, new_name: str = Form(...), db: Session = Depends(get_db)):
    old_path = _safe_model_path(name)
    if not os.path.exists(old_path):
        raise HTTPException(404, {"key": "error.modelNotFound", "fallback": "Модель не найдена"})
    clean = _sanitize_model_name(new_name)
    if not clean:
        raise HTTPException(400, "Некорректное имя")
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
                pass
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

@router.get("/api/models/bootstrap/status")
def bootstrap_status():
    return _bootstrap_snapshot()

@router.get("/api/models/bootstrap/events")
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
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.post("/api/models/download")
def download_model(payload: DownloadModelIn, db: Session = Depends(get_db)):
    size = payload.size if payload.size in ("n", "s", "m", "l", "x") else "n"
    pretrain = payload.pretrain if payload.pretrain in ("coco", "oiv7") else "oiv7"
    family = payload.family if payload.family in ("v8", "v11", "v26") else "v8"
    task = payload.task if payload.task in ("detect", "pose") else "detect"
    custom_name = payload.custom_name or ""
    if custom_name:
        clean = _sanitize_model_name(custom_name)
        if not clean:
            raise HTTPException(400, "Некорректное имя")
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
    t = threading.Thread(target=_download_model_worker, args=(size, pretrain, custom_name, True, family, task), daemon=True, name="model-downloader")
    with BOOTSTRAP_LOCK:
        _bootstrap_svc.BOOTSTRAP_THREAD = t
    t.start()
    return {"status": "started", "size": size, "pretrain": pretrain}

@router.post("/api/models/{name}/export_onnx")
def export_model_onnx(name: str, dynamic: bool = Form(True), db: Session = Depends(get_db)):
    from services.train_service import export_to_onnx
    p = _safe_model_path(name)
    if not os.path.exists(p):
        raise HTTPException(404, {"key": "error.modelNotFound", "fallback": "Model not found"})
    try:
        out = export_to_onnx(p, MODEL_DIR, dynamic=bool(dynamic))
    except Exception as e:
        raise HTTPException(500, f"ONNX export failed: {_safe_error_message(e)}")
    log_status("success", "model", f"ONNX export: {name} -> {os.path.basename(out)}")
    return {"status": "ok", "model": name, "onnx_path": out, "onnx_name": os.path.basename(out), "size": os.path.getsize(out) if os.path.exists(out) else 0}

# --- Stage 3.11 (moved from app.py) ---

import io as _io_ep
import zipfile as _zip_ep
from config import BASE_DIR as _BASE_DIR_ep


@router.get("/api/models/{name}/edge_package")
def download_edge_package(name: str, db: Session = Depends(get_db)):
    import os as _os_ep
    p = _safe_model_path(name)
    if not _os_ep.path.exists(p):
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
    if not _os_ep.path.exists(onnx_path):
        raise HTTPException(500, "ONNX file missing after export")
    edge_dir = _os_ep.path.join(_BASE_DIR_ep, "edge_runtime")
    edge_server = _os_ep.path.join(edge_dir, "edge_server.py")
    dockerfile = _os_ep.path.join(edge_dir, "Dockerfile.edge")
    if not _os_ep.path.exists(edge_server) or not _os_ep.path.exists(dockerfile):
        raise HTTPException(500, "edge_runtime files missing on server")
    buf = _io_ep.BytesIO()
    try:
        with _zip_ep.ZipFile(buf, "w", _zip_ep.ZIP_DEFLATED) as z:
            z.write(edge_server, "edge_package/edge_server.py")
            z.write(dockerfile, "edge_package/Dockerfile")
            z.write(onnx_path, "edge_package/model.onnx")
            z.writestr("edge_package/README.md",
                       "# DatasetBuilder Edge Runtime\n\n"
                       "Build: docker build -f Dockerfile -t db-edge:latest .\n"
                       "Run:   docker run --runtime nvidia --network host "
                       "-e EDGE_RTSP_URL=rtsp://... db-edge:latest\n")
    except Exception as e:
        log.exception("edge_package: zip build failed")
        raise HTTPException(500, f"Zip build failed: {_safe_error_message(e)}")
    buf.seek(0)
    onnx_name = _os_ep.path.basename(onnx_path)
    package_name = f"edge_package_{_os_ep.path.splitext(onnx_name)[0]}.zip"
    log_status("info", "export", f"Edge package: {name} -> {onnx_name}")
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={package_name}",
                 "Cache-Control": "no-store"})
