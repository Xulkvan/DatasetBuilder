"""Training helpers: pose dataset, metadata."""
import os
import csv
import json
import logging
import random
import shutil
from config import KEYPOINT_SCHEMA, KEYPOINT_FLIP_IDX
from models import Project, ImageModel, Annotation, Keypoint
from logger import utcnow
from version import APP_VERSION
import subprocess
import threading
import time
from sqlalchemy import func
from database import SessionLocal
from config import (
    MAX_TRAIN_LOG_LINES, MAX_EPOCH_PLAUSIBLE, _EPOCH_RE, _ANSI_RE,
    DEFAULT_OBJECT_CLASS, MODEL_DIR, BASE_DIR,
    SETTING_ACTIVE_MODEL, SETTING_ACTIVE_POSE_MODEL,
)
from logger import log_status
from services.bootstrap_service import _MODEL_ACTIVATION_LOCK
from services.file_service import _unique_model_name_from_disk
from services.ml_service import (
    _is_pose_model_name, _is_single_model_mode,
    _clear_yolo_cache, _invalidate_model_classes_cache,
)
from services.settings_service import set_setting

log = logging.getLogger("db")

def _ann_keypoints_as_list(db, ann_id, n_points, name_to_idx):
    rows = db.query(Keypoint).filter(Keypoint.annotation_id == ann_id).all()
    arr = [None] * n_points
    for kp in rows:
        idx = name_to_idx.get(kp.name)
        if idx is None: continue
        v = 2 if float(kp.visibility or 0) >= 0.5 else 1
        arr[idx] = (float(kp.x), float(kp.y), v)
    out = []
    for item in arr:
        if item is None: out += [0.0, 0.0, 0]
        else: out += [item[0], item[1], item[2]]
    return out

def _compute_flip_by_names(names):  # [PATCH:C23]
    """flip_idx for custom schema by L/R suffix matching (fallback: identity)."""
    result = list(range(len(names)))
    swaps = [
        ("_FL", "_FR"), ("_FR", "_FL"),
        ("_RL", "_RR"), ("_RR", "_RL"),
        ("_L", "_R"), ("_R", "_L"),
    ]
    for i, name in enumerate(names):
        for a, b in swaps:
            if name.endswith(a):
                mirror = name[:-len(a)] + b
                try:
                    result[i] = names.index(mirror)
                except ValueError:
                    pass
                break
    return result


def prepare_training_dataset_pose(db, project_id, run_dir):
    project = db.query(Project).filter(Project.id == project_id).first()
    object_class = (project.object_class if project else "pig") or "pig"
    class_yaml = object_class.replace("'", "''")
    # [FIX:v1341-backend] Применяем кастомную схему из БД.
    from config import get_keypoint_schema_for_project, KEYPOINT_FLIP_IDX as _DEFAULT_FLIP
    _schema = get_keypoint_schema_for_project(db, project_id)
    n_points = len(_schema)
    name_to_idx = {k[0]: i for i, k in enumerate(_schema)}

    dataset_dir = os.path.join(run_dir, "dataset")
    images_dir = os.path.join(dataset_dir, "images")
    labels_dir = os.path.join(dataset_dir, "labels")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(labels_dir, exist_ok=True)

    all_imgs = db.query(ImageModel).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)).all()
    pairs = []
    for im in all_imgs:
        anns = db.query(Annotation).filter(Annotation.image_id == im.id).all()
        if not anns: continue
        valid = []
        for a in anns:
            has_kp = db.query(Keypoint.id).filter(Keypoint.annotation_id == a.id).first()
            if has_kp: valid.append(a)
        if valid: pairs.append((im, valid))

    if not pairs:
        raise RuntimeError("В проекте нет изображений со скелетами. Разметь хотя бы один скелет (Shift+K).")

    # [STAGE2:pose-seed]
    _seed = int(getattr(project, "random_seed", 42) or 42)
    try:
        import numpy as _np
        _np.random.seed(_seed)
    except Exception:
        pass
    try:
        import torch as _torch
        _torch.manual_seed(_seed)
        if _torch.cuda.is_available():
            _torch.cuda.manual_seed_all(_seed)
    except Exception:
        pass
    import random as _random
    _random.seed(_seed)
    rng = _random.Random(_seed)
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
            dst = os.path.join(img_sub, str(im.id) + ".jpg")
            try: shutil.copy(im.path, dst)
            except OSError: continue
            label_lines = []
            for a in anns:
                kp_list = _ann_keypoints_as_list(db, a.id, n_points, name_to_idx)
                parts = []
                for idx_v, v in enumerate(kp_list):
                    if idx_v % 3 == 2: parts.append(str(int(v)))
                    else: parts.append("%.6f" % v)
                kp_str = " ".join(parts)
                label_lines.append("0 %.6f %.6f %.6f %.6f %s" % (a.x, a.y, a.w, a.h, kp_str))
            with open(os.path.join(lbl_sub, str(im.id) + ".txt"), "w", encoding="utf-8") as f:
                for ln in label_lines: print(ln, file=f)

    _dump(train_pairs, "train")
    _dump(val_pairs, "val")

    yaml_path = os.path.join(dataset_dir, "data.yaml")
    # [PATCH:C23] flip_idx by name matching (not just length)
    from config import KEYPOINT_SCHEMA as _KP_SCHEMA_REF
    _default_names = [k[0] for k in _KP_SCHEMA_REF]
    _schema_names = [k[0] for k in _schema]
    if _schema_names == _default_names:
        _flip = _DEFAULT_FLIP
    else:
        _flip = _compute_flip_by_names(_schema_names)
    flip_str = "[" + ", ".join(str(x) for x in _flip) + "]"
    val_ref = "images/val" if val_pairs else "images/train"

    with open(yaml_path, "w", encoding="utf-8") as f:
        print("path: " + dataset_dir, file=f)
        print("train: images/train", file=f)
        print("val: " + val_ref, file=f)
        print("nc: 1", file=f)
        print("names: ['" + class_yaml + "']", file=f)
        print("kpt_shape: [" + str(n_points) + ", 3]", file=f)
        print("flip_idx: " + flip_str, file=f)

    log.info("pose-датасет: %d train / %d val", len(train_pairs), len(val_pairs))
    return yaml_path

def _summarize_training_results(results_csv):
    if not os.path.exists(results_csv): return {}
    try:
        with open(results_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                if not clean.get("epoch"): continue
                rows.append(clean)
    except Exception:
        log.exception("parse results.csv failed")
        return {}
    if not rows: return {}
    def _f(row, key, default=0.0):
        try: return float(row.get(key, default) or default)
        except (TypeError, ValueError): return default
    best = None; best_val = -1.0
    for r in rows:
        v = _f(r, "metrics/mAP50-95(B)", 0.0)
        if v > best_val: best_val = v; best = r
    if best is None: return {}
    return {
        "best_epoch": int(_f(best, "epoch", 0)),
        "mAP50": _f(best, "metrics/mAP50(B)", 0.0),
        "mAP50_95": _f(best, "metrics/mAP50-95(B)", 0.0),
        "precision": _f(best, "metrics/precision(B)", 0.0),
        "recall": _f(best, "metrics/recall(B)", 0.0),
        "total_epochs": len(rows),
    }

def _save_training_metadata(run_dir, project_id, object_class, model_name, epochs, imgsz, annotated_count):
    results_csv = os.path.join(run_dir, "output", "train", "results.csv")
    summary = _summarize_training_results(results_csv)
    run_id = os.path.basename(run_dir).replace("train_", "")
    meta = {
        "run_id": run_id, "created_at": utcnow().isoformat(),
        "project_id": project_id, "object_class": object_class,
        "model_name": model_name, "epochs": epochs, "imgsz": imgsz,
        "annotated_count": annotated_count, "summary": summary,
    }
    try:
        with open(os.path.join(run_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        log.exception("save training metadata failed")
    return meta


# ============================================================================
# [STAGE2:export-to-onnx] Экспорт обученной YOLO-модели в ONNX.
# ============================================================================
def export_to_onnx(model_path: str, output_dir: str,
                   dynamic: bool = True) -> str:
    """Экспортирует .pt в ONNX (opset=12, simplify=True) и копирует
    результат в output_dir. Возвращает путь к .onnx-файлу."""
    import shutil as _shutil
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"model not found: {model_path}")
    os.makedirs(output_dir, exist_ok=True)
    from ultralytics import YOLO
    model = YOLO(model_path)
    exported_path = model.export(
        format="onnx", dynamic=bool(dynamic),
        simplify=True, opset=12,
    )
    if not exported_path or not os.path.exists(exported_path):
        raise RuntimeError(f"export failed, returned: {exported_path!r}")
    target = os.path.join(output_dir, os.path.basename(exported_path))
    if os.path.abspath(exported_path) != os.path.abspath(target):
        _shutil.copy(exported_path, target)
    log.info("export_to_onnx: %s -> %s", model_path, target)
    return target
# [/STAGE2:export-to-onnx]

# ============================================================================
# [STAGE4:train-service] Training state & thread.
# Moved from app.py to break the app.py <-> routers/api_v2.py cycle.
# ============================================================================
_SUBPROC_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_CREATE_NEW_PROCESS_GROUP = getattr(
    subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

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

def run_training_thread(args, run_dir, run_id, custom_name):
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
        # [PATCH:C15] ensure subprocess is dead and TRAIN_PROCESS is reset
        with TRAIN_LOCK:
            _proc_to_kill = TRAIN_PROCESS
            TRAIN_PROCESS = None
        if _proc_to_kill is not None:
            try:
                if _proc_to_kill.poll() is None:
                    _proc_to_kill.terminate()
                    try:
                        _proc_to_kill.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        _proc_to_kill.kill()
                        try:
                            _proc_to_kill.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            pass
            except Exception:
                log.exception("C15: process cleanup failed")
        with TRAIN_LOCK:
            TRAIN_STATE["finished_at"] = utcnow().isoformat()
            _final_train_status = TRAIN_STATE.get("status", "unknown")
        # [PATCH:STAGE4-F-08-counter-train]
        try:
            from services.metrics import train_runs_total as _tr_metric
            if _final_train_status in ("done", "error", "stopped"):
                _tr_metric.labels(status=_final_train_status).inc()
        except Exception:
            pass
        TRAIN_EVENT.set()
