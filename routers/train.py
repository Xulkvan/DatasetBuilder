"""routers/train.py — [PATCH:STAGE6-F03-4.2] Training endpoints."""
import os
import csv
import json
import threading
import asyncio
from datetime import datetime
from typing import Optional
from functools import lru_cache
import subprocess

from fastapi import APIRouter, HTTPException, Depends, Form
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session

from database import get_db
from config import RUNS_DIR, MAX_EPOCHS, MAX_FREEZE_LAYERS
from models import Project
from services.ml_service import get_active_model_path, get_active_pose_model_path, _count_annotations_with_skeleton
from services.train_service import TRAIN_STATE, TRAIN_LOCK, TRAIN_EVENT, _train_reset, _train_snapshot, prepare_training_dataset, prepare_training_dataset_pose, run_training_thread
from services import train_service as _train_svc
from services.rate_limiter import _limiter_train, _rate_limit
from services.file_service import _sanitize_model_name, _is_simple_filename
from logger import log_status, utcnow

router = APIRouter()

@router.post("/api/train/start")
def train_start(project_id: int = Form(...), base_model: str = Form("yolov8n.pt"),
                pretrain_dataset: str = Form("oiv7"), model_name: str = Form(""),
                epochs: int = Form(50), imgsz: int = Form(640), freeze: int = Form(8),
                lr0: float = Form(0.001), task: str = Form("detect"), family: str = Form("auto"),
                db: Session = Depends(get_db)):
    _rate_limit(_limiter_train, "local", {"key": "error.rateLimitedTrain", "fallback": "Слишком часто запускается обучение"})
    with TRAIN_LOCK:
        if TRAIN_STATE["status"] in ("running", "stopping", "preparing"):
            raise HTTPException(409, {"key": "error.alreadyTraining", "fallback": "Обучение уже идёт"})
        TRAIN_STATE["status"] = "preparing"
    try:
        proj = db.query(Project).filter(Project.id == project_id, Project.is_deleted.is_(False)).first()
        if not proj:
            raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
        epochs = max(1, min(MAX_EPOCHS, int(epochs)))
        imgsz = max(64, min(2048, int(imgsz)))
        custom_name = ""
        if model_name and model_name.strip():
            custom_name = _sanitize_model_name(model_name)
            if not custom_name:
                raise HTTPException(400, "Некорректное имя модели")
        task_clean = task if task in ("detect", "pose") else "detect"
        if task_clean == "pose":
            kp_count = _count_annotations_with_skeleton(db, project_id)
            if kp_count < 30:
                raise HTTPException(400, f"Для обучения pose нужно минимум 30 скелетов (сейчас {kp_count}).")
        if base_model == "__active__" or family == "__active__":
            active = (get_active_pose_model_path(db) if task_clean == "pose" else get_active_model_path(db))
            if not active:
                raise HTTPException(400, "Нет активной модели")
            model_path = active
        else:
            size_map = {"n": "n", "s": "s", "m": "m", "l": "l", "x": "x"}
            size = size_map.get(base_model, "n")
            _fam = family if family in ("v8", "v11", "v26") else ("v11" if task_clean == "pose" else "v8")
            prefix = "yolo11" if _fam == "v11" else ("yolo26" if _fam == "v26" else "yolov8")
            if task_clean == "pose":
                model_path = f"{prefix}{size}-pose.pt"
            elif pretrain_dataset == "oiv7" and _fam == "v8":
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
                "status": "running", "progress": 0.0, "current_epoch": 0, "total_epochs": epochs,
                "message": "Обучение запущено", "log_lines": [], "model_name": None, "project_id": project_id,
                "started_at": utcnow().isoformat(), "finished_at": None, "run_id": run_id, "task": task_clean,
            })
        TRAIN_EVENT.set()
        freeze_layers = max(0, min(MAX_FREEZE_LAYERS, int(freeze)))
        lr0_val = max(1e-5, min(0.1, float(lr0)))
        out_dir = os.path.join(run_dir, "output")
        yolo_task = "pose" if task_clean == "pose" else "detect"
        py_code = ("import sys, json; from ultralytics import YOLO; cfg = json.loads(sys.argv[1]); YOLO(cfg['model']).train(**cfg['kwargs'])")
        cfg = {"model": model_path, "task": yolo_task, "kwargs": {"data": yaml_path, "epochs": epochs, "imgsz": imgsz,
               "project": out_dir, "name": "train", "exist_ok": True, "device": "cpu", "verbose": True, "freeze": freeze_layers,
               "lr0": lr0_val, "patience": 20, "cos_lr": True, "warmup_epochs": 3}}
        import sys
        args = ([sys.executable, "--train-worker", json.dumps(cfg)] if getattr(sys, "frozen", False) else [sys.executable, "-c", py_code, json.dumps(cfg)])
        t = threading.Thread(target=run_training_thread, args=(args, run_dir, run_id, custom_name), daemon=True)
        t.start()
        return {"status": "started", "run_id": run_id, "planned_name": custom_name or f"train_{run_id}.pt"}
    except Exception:
        with TRAIN_LOCK:
            if TRAIN_STATE["status"] == "preparing":
                TRAIN_STATE["status"] = "idle"
        TRAIN_EVENT.set()
        raise

@router.get("/api/train/status")
def train_status(): return _train_snapshot()

@router.post("/api/train/stop")
def train_stop():
    with TRAIN_LOCK:
        if TRAIN_STATE["status"] != "running":
            return {"status": "not_running"}
        TRAIN_STATE["status"] = "stopping"
        proc = _train_svc.TRAIN_PROCESS
    TRAIN_EVENT.set()
    if proc is not None:
        import signal as _signal
        try:
            if os.name == "nt":
                try: proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired: proc.terminate()
            else:
                try: os.killpg(os.getpgid(proc.pid), _signal.SIGINT)
                except (ProcessLookupError, PermissionError, OSError):
                    try: proc.send_signal(_signal.SIGINT)
                    except Exception: pass
                try: proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try: os.killpg(os.getpgid(proc.pid), _signal.SIGTERM)
                    except Exception: pass
        except Exception: pass
    log_status("warning", "train", "Запрошена остановка обучения (last.pt сохранён)")
    return {"status": "stopping"}

@router.get("/api/train/events")
async def train_events():
    async def gen():
        snap = _train_snapshot()
        snap["live_epochs"] = []
        yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
        last = json.dumps(snap, ensure_ascii=False)
        while True:
            await asyncio.get_event_loop().run_in_executor(None, TRAIN_EVENT.wait, 0.6)
            TRAIN_EVENT.clear()
            snap = _train_snapshot()
            snap["live_epochs"] = _live_results_for_run(snap.get("run_id"))
            payload = json.dumps(snap, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if snap["status"] not in ("running", "stopping", "preparing"): break
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.post("/api/train/reset")
def train_reset():
    with TRAIN_LOCK:
        if TRAIN_STATE["status"] in ("running", "stopping", "preparing"):
            raise HTTPException(409, {"key": "error.trainingRunning", "fallback": "Нельзя сбросить, пока идёт обучение"})
    _train_reset()
    return {"status": "ok"}

@router.get("/api/train/runs")
def train_runs_list(project_id: Optional[int] = None): return {"items": _list_train_runs(project_id)}

@router.get("/api/train/runs/{folder}/metrics")
def train_run_metrics(folder: str):
    if not _is_simple_filename(folder) or not folder.startswith("train_"):
        raise HTTPException(400, "Некорректный прогон")
    run_dir = os.path.join(RUNS_DIR, folder)
    real = os.path.realpath(run_dir)
    if not real.startswith(os.path.realpath(RUNS_DIR) + os.sep):
        raise HTTPException(400, "Некорректный путь")
    if not os.path.isdir(real):
        raise HTTPException(404, "Прогон не найден")

    # metadata.json (best-effort; файл может отсутствовать у старых прогонов)
    meta = None
    meta_path = os.path.join(run_dir, "metadata.json")
    if os.path.exists(meta_path):
        try:
            mtime = os.path.getmtime(meta_path)
            meta = _read_run_metadata(RUNS_DIR, folder, mtime)
        except OSError:
            meta = None

    # results.csv → по-эпоховые метрики (mAP, losses)
    run_id = folder[len("train_"):] if folder.startswith("train_") else folder
    epochs = _live_results_for_run(run_id)

    return {"folder": folder, "metadata": meta, "epochs": epochs}

@router.get("/api/train/runs/{folder}/file/{name}")
def train_run_file(folder: str, name: str):
    if not _is_simple_filename(folder) or not folder.startswith("train_"):
        raise HTTPException(400, "Некорректный прогон")
    if not _is_simple_filename(name):
        raise HTTPException(400, "Некорректное имя файла")
    allowed = {"confusion_matrix.png", "confusion_matrix_normalized.png", "results.png", "val_batch0_pred.jpg",
               "val_batch1_pred.jpg", "val_batch2_pred.jpg", "train_batch0.jpg", "labels.jpg", "labels_correlogram.jpg",
               "F1_curve.png", "P_curve.png", "R_curve.png", "PR_curve.png"}
    if name not in allowed:
        raise HTTPException(400, "Файл не разрешён")
    path = os.path.join(RUNS_DIR, folder, "output", "train", name)
    if not os.path.exists(path):
        raise HTTPException(404, "Файл не найден")
    media = "image/png" if name.endswith(".png") else "image/jpeg"
    return FileResponse(path, media_type=media, headers={"Cache-Control": "public, max-age=3600"})

@lru_cache(maxsize=64)
def _read_run_metadata(runs_dir: str, folder: str, mtime: float):
    path = os.path.join(runs_dir, folder, "metadata.json")
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return None

def _list_train_runs(project_id: Optional[int] = None):
    if not os.path.isdir(RUNS_DIR): return []
    out = []
    for name in os.listdir(RUNS_DIR):
        if not name.startswith("train_"): continue
        run_dir = os.path.join(RUNS_DIR, name)
        if not os.path.isdir(run_dir): continue
        meta = None
        meta_path = os.path.join(run_dir, "metadata.json")
        if os.path.exists(meta_path):
            try:
                mtime = os.path.getmtime(meta_path)
                meta = _read_run_metadata(RUNS_DIR, name, mtime)
            except OSError: meta = None
        if meta is None:
            meta = {"run_id": name.replace("train_", ""), "project_id": None, "created_at": None, "model_name": None, "summary": {}}
        if project_id is not None and int(meta.get("project_id") or 0) != project_id: continue
        out.append({"run_id": meta.get("run_id") or name.replace("train_", ""), "folder": name, "project_id": meta.get("project_id"),
                    "created_at": meta.get("created_at"), "model_name": meta.get("model_name"), "summary": meta.get("summary") or {}})
    out.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return out

def _live_results_for_run(run_id: str) -> list:
    if not run_id: return []
    path = os.path.join(RUNS_DIR, f"train_{run_id}", "output", "train", "results.csv")
    if not os.path.exists(path): return []
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                if not clean.get("epoch"): continue
                def _f(k):
                    try: return float(clean.get(k, 0) or 0)
                    except Exception: return 0.0
                out.append({"epoch": int(_f("epoch")), "mAP50": _f("metrics/mAP50(B)"), "mAP50_95": _f("metrics/mAP50-95(B)"),
                            "train_box_loss": _f("train/box_loss"), "val_box_loss": _f("val/box_loss")})
    except Exception: pass
    return out
