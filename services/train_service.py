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
    # [FIX:v1341-backend] flip_idx: для кастомных схем — identity.
    _flip = _DEFAULT_FLIP if len(_schema) == len(_DEFAULT_FLIP) else list(range(n_points))
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
