"""[STAGE3:DEDUP-EXPORT] Helpers for YOLO/COCO export.

Вынесены из app.py в Stage 3 (3.1), чтобы:
  * убрать дублирующуюся логику из app.py,
  * дать routers/projects.py доступ к тем же helpers без циклических импортов,
  * упростить юнит-тестирование.

Публичные функции:
  * _build_letterbox_meta(images, fixed_size=FIXED_SIZE) -> dict
  * _split_images(images, split_spec) -> {'train','val','test'}
  * _kp_yolo_row(ann, kps_by_ann, schema, force_pad) -> str
  * _project_has_keypoints(db, project_id) -> bool
"""
from __future__ import annotations

import random

from sqlalchemy import func
from sqlalchemy.orm import Session

from config import FIXED_SIZE, KEYPOINT_SCHEMA
from models import Annotation, ImageModel, Keypoint


# ---------------------------------------------------------------------------
# Letterbox metadata
# ---------------------------------------------------------------------------
def _build_letterbox_meta(images, fixed_size=FIXED_SIZE) -> dict:
    """Letterbox-метаданные для каждого изображения.

    {image_id_str: {filename, original_*, new_*, pad_*, scale, transform_known}}
    """
    fw, fh = fixed_size
    out = {}
    for im in images:
        # transform_known = оба поля заданы
        _has_original = (
            bool(getattr(im, "original_width", None))
            and bool(getattr(im, "original_height", None))
        )
        if _has_original:
            ow = im.original_width
            oh = im.original_height
        else:
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
            "transform_known": _has_original,
        }
    return out


# ---------------------------------------------------------------------------
# Train/val/test split
# ---------------------------------------------------------------------------
def _split_images(images, split_spec):
    """Разбивает images на {'train','val','test'} по split_spec ('70,20,10')."""
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


# ---------------------------------------------------------------------------
# Keypoint helpers
# ---------------------------------------------------------------------------
def _kp_name_to_index(schema=None) -> dict:
    """{name: index} по переданной (или дефолтной) схеме."""
    if schema is None:
        schema = KEYPOINT_SCHEMA
    return {k[0]: i for i, k in enumerate(schema)}


def _kp_yolo_row(ann, kps_by_ann: dict, schema=None,
                 force_pad: bool = False) -> str:
    """YOLO-pose строка для одной аннотации.

    force_pad=True — писать пустые точки нулями даже если их нет,
    чтобы строка соответствовала kpt_shape в data.yaml.
    """
    kps = kps_by_ann.get(ann.id) or []
    base = f"0 {ann.x:.6f} {ann.y:.6f} {ann.w:.6f} {ann.h:.6f}"
    if not kps and not force_pad:
        return base
    if schema is None:
        schema = KEYPOINT_SCHEMA
    name2idx = _kp_name_to_index(schema)
    n = len(schema)
    arr = [None] * n
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


# ---------------------------------------------------------------------------
# Project-level checks
# ---------------------------------------------------------------------------
def _project_has_keypoints(db: Session, project_id: int) -> bool:
    """≥50% аннотаций проекта имеют скелет."""
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

# ============================================================================
# Stage 3.12: full YOLO / COCO export implementation (moved from app.py).
# ============================================================================
import os as _os_ex
import json as _json_ex
import threading as _th_ex
import uuid as _uuid_ex
import zipfile as _zip_ex
from contextlib import contextmanager as _ctx_mgr_ex


@_ctx_mgr_ex
def _atomic_zip_ex(zip_path: str):
    _tmp = zip_path + f".tmp_{_uuid_ex.uuid4().hex[:8]}"
    _zf = None
    try:
        _zf = _zip_ex.ZipFile(_tmp, "w", _zip_ex.ZIP_DEFLATED)
        yield _zf
        _zf.close()
        _zf = None
        _os_ex.replace(_tmp, zip_path)
    except Exception:
        if _zf is not None:
            try:
                _zf.close()
            except Exception:
                pass
        try:
            if _os_ex.path.exists(_tmp):
                _os_ex.remove(_tmp)
        except OSError:
            pass
        raise


def _iname_for_export_ex(img, naming, used):
    from services.file_service import _split_name_ext as _sne
    from config import INVALID_CHARS_RE as _ICR
    if naming == "original":
        stem, _ = _sne(img.filename)
        stem = _ICR.sub('_', stem).strip().rstrip('.') or str(img.id)
        base = stem
        n = 1
        while stem in used:
            stem = f"{base} ({n})"
            n += 1
        used.add(stem)
        return f"{stem}.jpg"
    return f"{img.id}.jpg"


def _cleanup_old_exports_ex(prefix: str, keep: int = 20):
    from config import EXPORT_DIR as _ED
    try:
        files = [(_os_ex.path.join(_ED, f),
                  _os_ex.path.getmtime(_os_ex.path.join(_ED, f)))
                 for f in _os_ex.listdir(_ED)
                 if f.startswith(prefix) and f.endswith(".zip")]
        files.sort(key=lambda x: x[1], reverse=True)
        for p, _ in files[keep:]:
            try:
                _os_ex.remove(p)
            except OSError:
                pass
    except Exception:
        pass


def export_yolo_impl(db, project_id: int, naming: str = "numbered",
                     split: str = "none", force_pose: bool = False,
                     include_meta: bool = False) -> str:
    """Stage 3.12 — full body of export_yolo, returns zip_path."""
    from models import Project, ImageModel, Annotation, Keypoint
    from services.export_service import (
        _split_images, _kp_yolo_row, _project_has_keypoints,
        _build_letterbox_meta,
    )
    from config import EXPORT_DIR, DEFAULT_OBJECT_CLASS, KEYPOINT_SCHEMA
    from config import get_keypoint_schema_for_project
    from logger import utcnow
    from collections import defaultdict

    def _chunks_local(seq, n=500):
        for i in range(0, len(seq), n):
            yield seq[i:i + n]

    def _anns_with_keypoints_local(db, image_ids):
        if not image_ids:
            return {}
        ann_ids = []
        for _c in _chunks_local(image_ids, 500):
            for row in db.query(Annotation.id).filter(
                    Annotation.image_id.in_(_c)).all():
                ann_ids.append(row.id)
        if not ann_ids:
            return {}
        out = defaultdict(list)
        for _c in _chunks_local(ann_ids, 500):
            for kp in db.query(Keypoint).filter(
                    Keypoint.annotation_id.in_(_c)).all():
                out[kp.annotation_id].append(kp)
        return out

    if naming not in ("original", "numbered"):
        naming = "numbered"
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        from fastapi import HTTPException as _HTTPE
        raise _HTTPE(404, {"key": "error.projectNotFound",
                           "fallback": "Project not found"})
    object_class = proj.object_class or DEFAULT_OBJECT_CLASS
    class_yaml = object_class.replace("'", "''")
    images = (db.query(ImageModel)
                .filter(ImageModel.project_id == project_id,
                        ImageModel.is_deleted.is_(False)).all())
    if not images:
        from fastapi import HTTPException as _HTTPE
        raise _HTTPE(404, {"key": "error.noImages", "fallback": "No images"})
    buckets = _split_images(images, split)
    use_split = (split and split != "none"
                 and (len(buckets["val"]) + len(buckets["test"])) > 0)
    zip_path = _os_ex.path.join(
        EXPORT_DIR, f"yolo_project_{project_id}_{naming}_{split}.zip")
    used = set()
    with _atomic_zip_ex(zip_path) as z:
        _use_pose_for_yaml = force_pose or _project_has_keypoints(db, project_id)
        _kp_extra = ""
        if _use_pose_for_yaml:
            try:
                _schema_yaml = get_keypoint_schema_for_project(db, project_id)
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
        z.writestr("data.yaml", data_yaml)
        try:
            from services.dataset_card_service import generate_dataset_card
            z.writestr("README.md", generate_dataset_card(db, project_id))
        except Exception:
            pass
        try:
            from services.versioning_service import calculate_dataset_hash
            _ds_hash = calculate_dataset_hash(db, project_id)
            z.writestr("dataset_info.json", _json_ex.dumps({
                "hash": _ds_hash, "project_id": project_id,
                "object_class": object_class,
                "exported_at": utcnow().isoformat(),
                "naming": naming, "split": split,
            }, ensure_ascii=False, indent=2))
        except Exception:
            pass
        attr_rows = ["image_filename,annotation_index,behavior,animal_id,timestamp_sec"]
        use_pose = _use_pose_for_yaml
        img_ids = [im.id for im in images]
        kps_by_ann = _anns_with_keypoints_local(db, img_ids) if use_pose else {}
        _export_schema = (get_keypoint_schema_for_project(db, project_id)
                          if use_pose else KEYPOINT_SCHEMA)
        _iname_map = {}
        for _bucket_images in buckets.values():
            for _img in _bucket_images:
                _iname_map[_img.id] = _iname_for_export_ex(_img, naming, used)
        _all_img_ids = [im.id for im in images]
        _anns_by_image = defaultdict(list)
        _kp_by_ann = defaultdict(list)
        for _id_chunk in _chunks_local(_all_img_ids, 500):
            for _a in db.query(Annotation).filter(
                    Annotation.image_id.in_(_id_chunk)).all():
                _anns_by_image[_a.image_id].append(_a)
        _ann_ids_all = [a.id for lst in _anns_by_image.values() for a in lst]
        for _ann_chunk in _chunks_local(_ann_ids_all, 500):
            for _k in db.query(Keypoint).filter(
                    Keypoint.annotation_id.in_(_ann_chunk)).all():
                _kp_by_ann[_k.annotation_id].append(_k)
        for bucket_name, bucket_images in buckets.items():
            if not bucket_images:
                continue
            sub_img = f"images/{bucket_name}" if use_split else "images"
            sub_lbl = f"labels/{bucket_name}" if use_split else "labels"
            for img in bucket_images:
                if not img.path or not _os_ex.path.exists(img.path):
                    continue
                iname = _iname_map[img.id]
                z.write(img.path, f"{sub_img}/{iname}")
                anns = _anns_by_image.get(img.id, [])
                if use_pose:
                    lines = [_kp_yolo_row(a, kps_by_ann, _export_schema,
                                           force_pad=True) for a in anns]
                else:
                    lines = [f"0 {a.x:.6f} {a.y:.6f} {a.w:.6f} {a.h:.6f}"
                             for a in anns]
                z.writestr(f"{sub_lbl}/{_os_ex.path.splitext(iname)[0]}.txt",
                           "\n".join(lines))
                ts_str = ("" if img.timestamp_sec is None
                          else f"{img.timestamp_sec:.3f}")
                for ai, a in enumerate(anns):
                    beh = (a.behavior or "").replace(",", " ")
                    aid = "" if a.animal_id is None else str(a.animal_id)
                    attr_rows.append(f"{iname},{ai},{beh},{aid},{ts_str}")
        if len(attr_rows) > 1:
            z.writestr("attributes.csv", "\n".join(attr_rows))
        kp_rows = ["image_filename,annotation_index,keypoint_name,x,y,visibility"]
        for bucket_name, bucket_images in buckets.items():
            if not bucket_images:
                continue
            for img in bucket_images:
                iname = _iname_map[img.id]
                anns = _anns_by_image.get(img.id, [])
                for ai, a in enumerate(anns):
                    for kp in _kp_by_ann.get(a.id, []):
                        kp_rows.append(f"{iname},{ai},{kp.name},"
                                        f"{kp.x:.6f},{kp.y:.6f},{kp.visibility:.3f}")
        if len(kp_rows) > 1:
            z.writestr("keypoints.csv", "\n".join(kp_rows))
        if include_meta:
            try:
                _meta = _build_letterbox_meta(images)
                z.writestr("dataset_meta.json",
                           _json_ex.dumps(_meta, ensure_ascii=False, indent=2))
            except Exception:
                pass
    _cleanup_old_exports_ex("yolo_project_")
    try:
        _wh_size = (_os_ex.path.getsize(zip_path)
                    if _os_ex.path.exists(zip_path) else 0)
        def _fire(_pid=project_id, _fmt="yolo", _size=_wh_size):
            try:
                from services.webhook_service import dispatch_event as _wh
                _wh(None, _pid, "dataset.exported",
                    {"format": _fmt, "size": _size})
            except Exception:
                pass
        _th_ex.Thread(target=_fire, daemon=True,
                       name=f"wh-export-{project_id}").start()
    except Exception:
        pass
    return zip_path


def export_coco_impl(db, project_id: int, naming: str = "numbered",
                     split: str = "none", include_meta: bool = False) -> str:
    """Stage 3.12 — full body of export_coco, returns zip_path."""
    from models import Project, ImageModel, Annotation, Keypoint
    from services.export_service import (
        _split_images, _project_has_keypoints, _build_letterbox_meta,
    )
    from config import EXPORT_DIR, DEFAULT_OBJECT_CLASS, KEYPOINT_SCHEMA
    from config import get_keypoint_schema_for_project
    from collections import defaultdict

    def _chunks_local(seq, n=500):
        for i in range(0, len(seq), n):
            yield seq[i:i + n]

    def _anns_with_keypoints_local(db, image_ids):
        if not image_ids:
            return {}
        ann_ids = []
        for _c in _chunks_local(image_ids, 500):
            for row in db.query(Annotation.id).filter(
                    Annotation.image_id.in_(_c)).all():
                ann_ids.append(row.id)
        if not ann_ids:
            return {}
        out = defaultdict(list)
        for _c in _chunks_local(ann_ids, 500):
            for kp in db.query(Keypoint).filter(
                    Keypoint.annotation_id.in_(_c)).all():
                out[kp.annotation_id].append(kp)
        return out

    if naming not in ("original", "numbered"):
        naming = "numbered"
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        from fastapi import HTTPException as _HTTPE
        raise _HTTPE(404, {"key": "error.projectNotFound",
                           "fallback": "Project not found"})
    object_class = proj.object_class or DEFAULT_OBJECT_CLASS
    images = (db.query(ImageModel)
                .filter(ImageModel.project_id == project_id,
                        ImageModel.is_deleted.is_(False)).all())
    if not images:
        from fastapi import HTTPException as _HTTPE
        raise _HTTPE(404, {"key": "error.noImages", "fallback": "No images"})
    buckets = _split_images(images, split)
    use_split = (split and split != "none"
                 and (len(buckets["val"]) + len(buckets["test"])) > 0)
    zip_path = _os_ex.path.join(
        EXPORT_DIR, f"coco_project_{project_id}_{naming}_{split}.zip")
    used = set()
    with _atomic_zip_ex(zip_path) as z:
        use_kp = _project_has_keypoints(db, project_id)
        _img_ids_all = [im.id for im in images]
        _kps_by_ann = (_anns_with_keypoints_local(db, _img_ids_all)
                       if use_kp else {})
        _export_schema = (get_keypoint_schema_for_project(db, project_id)
                          if use_kp else KEYPOINT_SCHEMA)
        _kp_names = [k[0] for k in _export_schema]
        _kp_index = {k[0]: i for i, k in enumerate(_export_schema)}
        _kp_skeleton = [[_kp_index[par] + 1, _kp_index[ch] + 1]
                        for (ch, _ru, _en, par) in _export_schema if par]
        _iname_map = {}
        for _bucket_images in buckets.values():
            for _img in _bucket_images:
                _iname_map[_img.id] = _iname_for_export_ex(_img, naming, used)
        _all_img_ids = [im.id for im in images]
        _anns_by_image = defaultdict(list)
        for _id_chunk in _chunks_local(_all_img_ids, 500):
            for _a in db.query(Annotation).filter(
                    Annotation.image_id.in_(_id_chunk)).all():
                _anns_by_image[_a.image_id].append(_a)
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
                if not img.path or not _os_ex.path.exists(img.path):
                    continue
                iname = _iname_map[img.id]
                coco["images"].append({"id": img.id, "file_name": iname,
                                        "width": img.width,
                                        "height": img.height})
                anns = _anns_by_image.get(img.id, [])
                for a in anns:
                    x = a.x * img.width
                    y = a.y * img.height
                    w = a.w * img.width
                    h = a.h * img.height
                    ann = {"id": ann_id, "image_id": img.id,
                           "category_id": 1,
                           "bbox": [x, y, w, h], "area": w * h,
                           "iscrowd": 0}
                    if a.confidence is not None:
                        ann["score"] = a.confidence
                    if use_kp:
                        kps = _kps_by_ann.get(a.id) or []
                        n = len(_export_schema)
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
            z.writestr(f"coco_{bucket_name}.json",
                       _json_ex.dumps(coco, ensure_ascii=False, indent=2))
        if include_meta:
            try:
                _meta = _build_letterbox_meta(images)
                z.writestr("dataset_meta.json",
                           _json_ex.dumps(_meta, ensure_ascii=False, indent=2))
            except Exception:
                pass
    _cleanup_old_exports_ex("coco_project_")
    try:
        _wh_size = (_os_ex.path.getsize(zip_path)
                    if _os_ex.path.exists(zip_path) else 0)
        def _fire(_pid=project_id, _fmt="coco", _size=_wh_size):
            try:
                from services.webhook_service import dispatch_event as _wh
                _wh(None, _pid, "dataset.exported",
                    {"format": _fmt, "size": _size})
            except Exception:
                pass
        _th_ex.Thread(target=_fire, daemon=True,
                       name=f"wh-export-{project_id}").start()
    except Exception:
        pass
    return zip_path
