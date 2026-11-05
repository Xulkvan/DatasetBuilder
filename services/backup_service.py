"""[PATCH:STAGE2-F-11] Backup service: create_backup + restore_backup.

Извлечено из app.py::backup_project. Формат (обратно совместим):
  meta.json / images_index.json / annotations.json / tags.json /
  images/<old_image_id>.jpg

create_backup используется:
  * app.py::backup_project (ручной бэкап проекта);
  * pipeline_service::_stage_autolabel (перед replace — pre_replace_backup).

restore_backup используется rollback-эндпоинтом.
"""
from __future__ import annotations

import json
import os
import re
import uuid
import zipfile
from collections import defaultdict

from sqlalchemy.orm import Session

import config as _cfg  # [FIX:STAGE2-backup-dyn]
from config import DEFAULT_OBJECT_CLASS
from version import APP_VERSION
from logger import utcnow, log_status
from models import (
    Project, ImageModel, Annotation, Keypoint, Tag, ImageTag,
)

import logging
log = logging.getLogger("db")


def _chunks(seq, n=500):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def create_backup(db: Session, project_id: int,
                  prefix: str = "backup_project") -> tuple:
    """Создаёт zip-бэкап проекта.

    Возвращает (zip_path: str, meta: dict) — meta содержит images_count,
    tags_count, annotations_count, object_class.
    """
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise ValueError(f"Project {project_id} not found")
    safe_name = (re.sub(r'[^A-Za-z0-9_\-]+', '_', proj.name)
                 .strip('_')[:60] or f"project_{project_id}")
    ts = utcnow().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{prefix}_{project_id}_{safe_name}.zip"
    zip_path = os.path.join(_cfg.BACKUP_DIR, zip_name)
    tmp_path = zip_path + ".part"

    images = (db.query(ImageModel)
                .filter(ImageModel.project_id == project_id,
                        ImageModel.is_deleted.is_(False)).all())
    ids = [im.id for im in images]

    annotations: dict = defaultdict(list)
    kp_by_ann: dict = defaultdict(list)
    all_ann_rows = []
    if ids:
        for chunk in _chunks(ids, 500):
            for a in (db.query(Annotation)
                        .filter(Annotation.image_id.in_(chunk)).all()):
                all_ann_rows.append(a)
        ann_ids = [a.id for a in all_ann_rows]
        for chunk in _chunks(ann_ids, 500):
            for kp in (db.query(Keypoint)
                         .filter(Keypoint.annotation_id.in_(chunk)).all()):
                kp_by_ann[kp.annotation_id].append({
                    "name": kp.name, "x": kp.x, "y": kp.y,
                    "visibility": kp.visibility,
                })
        for a in all_ann_rows:
            annotations[str(a.image_id)].append({
                "x": a.x, "y": a.y, "w": a.w, "h": a.h,
                "label": a.label, "confidence": a.confidence,
                "frozen": bool(a.is_frozen),
                "behavior": a.behavior,
                "animal_id": a.animal_id,
                "keypoints": kp_by_ann.get(a.id, []),
            })

    tags = db.query(Tag).filter(Tag.project_id == project_id).all()
    tags_out = []
    for t in tags:
        img_ids = [it.image_id for it in
                   db.query(ImageTag).filter(ImageTag.tag_id == t.id).all()]
        tags_out.append({"id": t.id, "name": t.name,
                         "color": t.color, "image_ids": img_ids})

    meta = {
        "app_version": APP_VERSION, "backup_version": 1, "is_backup": True,
        "created_at": ts,
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

    # [FIX:STAGE2-cb-mkdir] Гарантируем существование BACKUP_DIR
    # (не полагаемся на import-time os.makedirs в config.py — если
    # DATA_ROOT пересоздан, директории может не быть).
    try:
        os.makedirs(_cfg.BACKUP_DIR, exist_ok=True)
    except OSError:
        pass
    try:
        with zipfile.ZipFile(tmp_path, "w",
                             zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr("meta.json",
                       json.dumps(meta, ensure_ascii=False, indent=2))
            z.writestr("images_index.json",
                       json.dumps(images_index, ensure_ascii=False, indent=2))
            z.writestr("annotations.json",
                       json.dumps(dict(annotations), ensure_ascii=False))
            z.writestr("tags.json",
                       json.dumps(tags_out, ensure_ascii=False))
            for im in images:
                if os.path.exists(im.path):
                    z.write(im.path, f"images/{im.id}.jpg")
        os.replace(tmp_path, zip_path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise

    log_status("success", "backup",
               f"Backup проекта «{proj.name}» (id={project_id}, "
               f"prefix={prefix}): {len(images)} фото")
    return zip_path, meta


def restore_backup(db: Session, project_id: int, zip_path: str) -> dict:
    """Восстанавливает проект из zip-бэкапа (create_backup).

    Полностью удаляет текущие images/annotations/keypoints и заново
    разворачивает содержимое бэкапа. Проект (Project) сохраняется.
    """
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise ValueError(f"Project {project_id} not found")
    if not os.path.exists(zip_path):
        raise FileNotFoundError(zip_path)

    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        meta = (json.loads(z.read("meta.json").decode("utf-8"))
                if "meta.json" in names else {})
        images_index = (json.loads(z.read("images_index.json").decode("utf-8"))
                        if "images_index.json" in names else [])
        annotations = (json.loads(z.read("annotations.json").decode("utf-8"))
                       if "annotations.json" in names else {})
        tags_data: list = []
        if "tags.json" in names:
            try:
                tags_data = json.loads(z.read("tags.json").decode("utf-8"))
            except Exception:
                tags_data = []

        # 1) Удаляем текущее содержимое
        old_img_ids = [r.id for r in
                       db.query(ImageModel.id)
                         .filter(ImageModel.project_id == project_id).all()]
        if old_img_ids:
            old_ann_ids = [r.id for r in
                           db.query(Annotation.id)
                             .filter(Annotation.image_id.in_(old_img_ids)).all()]
            if old_ann_ids:
                db.query(Keypoint)                     .filter(Keypoint.annotation_id.in_(old_ann_ids))                     .delete(synchronize_session=False)
            db.query(Annotation)                 .filter(Annotation.image_id.in_(old_img_ids))                 .delete(synchronize_session=False)
            db.query(ImageTag)                 .filter(ImageTag.image_id.in_(old_img_ids))                 .delete(synchronize_session=False)
            db.query(ImageModel)                 .filter(ImageModel.id.in_(old_img_ids))                 .delete(synchronize_session=False)
            db.commit()

        # 2) Project metadata
        if meta.get("object_class"):
            proj.object_class = meta["object_class"]
        if meta.get("object_class_source"):
            proj.object_class_source = meta["object_class_source"]

        # 3) Images
        # [FIX:STAGE2-rb] Создаём ImageModel даже если файла нет в zip —
        # иначе rollback теряет разметку "виртуальных" картинок (запись
        # в БД есть, файла на диске нет — например, из тестов или после
        # ручного удаления uploads/*.jpg). Файл пишем только если он в
        # архиве; метаданные (bbox/keypoints/behavior) восстанавливаем
        # всегда — это и есть смысл rollback.
        old_to_new: dict = {}
        for idx in images_index:
            try:
                old_id = int(idx["id"])
            except (KeyError, ValueError, TypeError):
                continue
            zname = f"images/{old_id}.jpg"
            new_fname = f"{uuid.uuid4().hex}.jpg"
            new_path = os.path.join(_cfg.UPLOAD_DIR, new_fname)
            file_written = False
            if zname in names:
                try:
                    with open(new_path, "wb") as f:
                        f.write(z.read(zname))
                    file_written = True
                except OSError:
                    pass
            try:
                fsize = os.path.getsize(new_path) if file_written else 0
            except OSError:
                fsize = 0
            im = ImageModel(
                project_id=project_id,
                filename=idx.get("filename") or new_fname,
                path=new_path,
                width=idx.get("width") or 640,
                height=idx.get("height") or 640,
                is_deleted=False,
                phash=idx.get("phash"),
                is_hard=bool(idx.get("is_hard")),
                created_at=utcnow(),
                file_size=fsize,
            )
            db.add(im)
            db.flush()
            old_to_new[old_id] = im.id
            if file_written:
                try:
                    from services.image_service import _queue_thumb
                    from typing import cast as _cast_q
                    # [FIX:STAGE2-mypy-thumb] im.id/im.path видны mypy
                    # как Column[int]/Column[str]; после flush() это int/str.
                    _queue_thumb(_cast_q(int, im.id),
                                 _cast_q(str, im.path))
                except Exception:
                    pass

        # 4) Annotations + Keypoints
        n_ann = 0
        for old_img_str, anns_list in (annotations or {}).items():
            try:
                old_img_id = int(old_img_str)
            except (ValueError, TypeError):
                continue
            new_img_id = old_to_new.get(old_img_id)
            if not new_img_id:
                continue
            for a in anns_list or []:
                ann = Annotation(
                    image_id=new_img_id,
                    x=float(a.get("x", 0)),
                    y=float(a.get("y", 0)),
                    w=float(a.get("w", 0)),
                    h=float(a.get("h", 0)),
                    label=a.get("label") or "pig",
                    confidence=a.get("confidence"),
                    is_frozen=bool(a.get("frozen")),
                    behavior=a.get("behavior"),
                    animal_id=a.get("animal_id"),
                )
                db.add(ann)
                db.flush()
                n_ann += 1
                for kp in (a.get("keypoints") or []):
                    try:
                        db.add(Keypoint(
                            annotation_id=ann.id,
                            name=str(kp.get("name") or "nose"),
                            x=float(kp.get("x", 0)),
                            y=float(kp.get("y", 0)),
                            visibility=float(kp.get("visibility", 1.0)),
                        ))
                    except Exception:
                        continue

        # 5) Tags (best-effort)
        if tags_data:
            new_tag_ids: dict = {}
            for t in tags_data:
                try:
                    nt = Tag(project_id=project_id,
                             name=t.get("name") or "tag",
                             color=t.get("color") or "#0071e3")
                    db.add(nt)
                    db.flush()
                    new_tag_ids[int(t.get("id", 0) or 0)] = nt.id
                except Exception:
                    continue
            for t in tags_data:
                try:
                    old_tid = int(t.get("id", 0) or 0)
                except (ValueError, TypeError):
                    continue
                new_tid = new_tag_ids.get(old_tid)
                if not new_tid:
                    continue
                for old_iid in (t.get("image_ids") or []):
                    try:
                        new_iid = old_to_new.get(int(old_iid))
                    except (ValueError, TypeError):
                        continue
                    if new_iid:
                        db.add(ImageTag(image_id=new_iid, tag_id=new_tid))

        db.commit()

    return {"restored_images": len(old_to_new),
            "restored_annotations": n_ann}
