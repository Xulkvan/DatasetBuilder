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

import config as _cfg
from config import DEFAULT_OBJECT_CLASS
from version import APP_VERSION
from logger import utcnow, log_status
from models import (
    Project, ImageModel, Annotation, Keypoint, Tag, ImageTag,
)

import logging
from sqlalchemy import func as _func_bs
log = logging.getLogger("db")

# Marker: indicates the streaming export patch (STAGE6) has been applied.
# Used only for idempotency — no side effects.
_streaming_marker = True


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

    # Гарантируем существование BACKUP_DIR
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

    _created_paths: list[str] = []
    try:
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

        # Отслеживаем созданные файлы для cleanup при rollback
        _created_paths: list[str] = []
        # 1) Удаляем текущее содержимое (без commit — единая транзакция)
        old_img_ids = [r.id for r in
                       db.query(ImageModel.id)
                         .filter(ImageModel.project_id == project_id).all()]
        if old_img_ids:
            old_ann_ids = [r.id for r in
                           db.query(Annotation.id)
                             .filter(Annotation.image_id.in_(old_img_ids)).all()]
            if old_ann_ids:
                db.query(Keypoint).filter(Keypoint.annotation_id.in_(old_ann_ids)).delete(synchronize_session=False)
            db.query(Annotation).filter(Annotation.image_id.in_(old_img_ids)).delete(synchronize_session=False)
            db.query(ImageTag).filter(ImageTag.image_id.in_(old_img_ids)).delete(synchronize_session=False)
            db.query(ImageModel).filter(ImageModel.id.in_(old_img_ids)).delete(synchronize_session=False)

        # 2) Project metadata
        if meta.get("object_class"):
            proj.object_class = meta["object_class"]
        if meta.get("object_class_source"):
            proj.object_class_source = meta["object_class_source"]

        # 3) Images
        # Создаём ImageModel даже если файла нет в zip —
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
                    _created_paths.append(new_path)
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
                    # im.id/im.path видны mypy
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

        # commit + инвалидация кэшей
        db.commit()
    except Exception:
        db.rollback()
        for _p in (_created_paths or []):
            try:
                if os.path.exists(_p):
                    os.remove(_p)
            except OSError:
                pass
        raise
    finally:
        # инвалидация кэшей phash/stats
        try:
            from services.image_service import (
                _invalidate_phash_index, _invalidate_stats_cache,
            )
            _invalidate_phash_index(project_id)
            _invalidate_stats_cache(project_id)
        except Exception:
            pass

    return {"restored_images": len(old_to_new),
            "restored_annotations": n_ann}

# ═══════════════════════════════════════════════════════════════════════
# Full project backup export (Stage 1)
# ═══════════════════════════════════════════════════════════════════════
from datetime import datetime
from models import (
    Video, DatasetVersion, BlurRegion, BehaviorValidation,
    ProjectKeypointSchema, User, Stream, Webhook,
)
from schemas_backup import (
    Manifest, ManifestCounts, ManifestOptions,
    ProjectEntry, VideoEntry, ImageEntry, AnnotationEntry, KeypointEntry,
    TagEntry, ImageTagEntry, VersionEntry, BlurRegionEntry,
    BehaviorValidationEntry, KeypointSchemaEntry, StreamEntry, WebhookEntry,
)


def _write_json_stream(zf, arcname: str, items_iter) -> int:
    count = 0
    with zf.open(arcname, "w") as f:
        f.write(b"[")
        first = True
        for item in items_iter:
            if not first:
                f.write(b",")
            if hasattr(item, "model_dump_json"):
                f.write(item.model_dump_json().encode("utf-8"))
            else:
                f.write(json.dumps(item, ensure_ascii=False).encode("utf-8"))
            first = False
            count += 1
        f.write(b"]")
    return count


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


def _ext_from_path(path: str, default: str) -> str:
    if not path:
        return default
    ext = os.path.splitext(path)[1].lower()
    return ext if ext else default


def _strip_stream_credentials(url: str) -> tuple[str, bool]:
    """Strip user:pass@ from a stream URL. Returns (clean_url, had_creds).

    Full backups must be restorable; import_full_project rejects
    streams.json entries with embedded credentials (see
    services/backup_validate.py). Credentials must be re-entered
    manually after import (per ADR-0011).
    """
    from urllib.parse import urlparse as _urlparse, urlunparse as _urlunparse
    try:
        p = _urlparse(url or "")
    except (ValueError, AttributeError):
        return (url, False)
    if not (p.username or p.password):
        return (url, False)
    try:
        host = p.hostname or ""
        try:
            port = p.port
        except ValueError:
            port = None
        if port:
            host = f"{host}:{port}"
        clean = _urlunparse((p.scheme, host, p.path or "",
                             p.params or "", p.query or "",
                             p.fragment or ""))
        return (clean, True)
    except (ValueError, AttributeError):
        return (url, False)


def export_full_project(
    db: Session, project_id: int, *,
    include_videos: bool = True,
    include_versions: bool = True,
    include_blur_regions: bool = True,
    include_behavior_validations: bool = True,
    include_streams: bool = False,
    include_webhooks: bool = False,
    out_path: str | None = None,
    progress_cb=None,
) -> dict:
    project = db.query(Project).filter(
        Project.id == project_id, Project.is_deleted.is_(False)).first()
    if not project:
        raise ValueError(f"Project {project_id} not found")

    if out_path is None:
        out_path = os.path.join(
            _cfg.BACKUP_DIR,
            f"datasetbuilder_full_{project_id}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
            f"{uuid.uuid4().hex[:6]}.zip",
        )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp_path = out_path + ".part"

    warnings: list[str] = []

    project_entry = ProjectEntry(
        name=project.name,
        object_class=project.object_class or "pig",
        object_class_source=project.object_class_source or "list",
        data_retention_days=int(project.data_retention_days or 0),
        trash_ttl_days_override=project.trash_ttl_days_override,
        thumbnail_size=project.thumbnail_size,
        default_zoom=project.default_zoom,
        random_seed=int(project.random_seed or 42),
        auto_blur_enabled=bool(project.auto_blur_enabled),
        auto_blur_classes=project.auto_blur_classes,
    )

    schema_row = (db.query(ProjectKeypointSchema)
                    .filter(ProjectKeypointSchema.project_id == project_id)
                    .first())
    schema_entry = None
    if schema_row and schema_row.schema_json:
        try:
            parsed = json.loads(schema_row.schema_json)
            if isinstance(parsed, list) and parsed:
                schema_entry = KeypointSchemaEntry(schema_list=parsed)
        except Exception:
            warnings.append("keypoint schema unparsable, skipped")

    videos = []
    if include_videos:
        for v in db.query(Video).filter(
                Video.project_id == project_id,
                Video.is_deleted.is_(False)).all():
            videos.append(VideoEntry(
                old_id=v.id, filename=v.filename,
                fps=v.fps, frame_count=v.frame_count,
                duration_sec=v.duration_sec, extract_fps=v.extract_fps,
                images_count=v.images_count, created_at=_iso(v.created_at),
            ))

    user_by_id = {u.id: u.username for u in db.query(User).all()}

    def _images_iter():
        for im in (db.query(ImageModel)
                     .filter(ImageModel.project_id == project_id,
                             ImageModel.is_deleted.is_(False))
                     .order_by(ImageModel.id)
                     .yield_per(1000)):
            ext = _ext_from_path(im.path, ".jpg")
            yield ImageEntry(
                old_id=im.id,
                old_video_id=im.video_id,
                filename=im.filename,
                frame_index=im.frame_index,
                timestamp_sec=im.timestamp_sec,
                width=im.width, height=im.height,
                original_width=im.original_width,
                original_height=im.original_height,
                is_hard=bool(im.is_hard),
                is_stream_frame=bool(getattr(im, "is_stream_frame", False)),
                phash=im.phash,
                created_at=_iso(im.created_at),
                file_size=im.file_size,
                revision=int(getattr(im, "revision", 1) or 1),
                review_status=im.review_status or "unassigned",
                assigned_to_username=(
                    user_by_id.get(im.assigned_to) if im.assigned_to else None
                ),
                reviewed_by_username=(
                    user_by_id.get(im.reviewed_by) if im.reviewed_by else None
                ),
                review_comment=im.review_comment,
                reviewed_at=_iso(im.reviewed_at),
                file_ext=ext,
            )

    # Only IDs kept in memory (needed for chunked annotations/keypoints queries)
    image_ids = [
        im_id for (im_id,) in
        (db.query(ImageModel.id)
           .filter(ImageModel.project_id == project_id,
                   ImageModel.is_deleted.is_(False))
           .order_by(ImageModel.id)
           .all())
    ]

    # Collect annotation IDs first (small memory) — needed for keypoints + bvals
    ann_ids: list[int] = []
    for chunk in _chunks(image_ids):
        for (aid,) in (db.query(Annotation.id)
                         .filter(Annotation.image_id.in_(chunk))
                         .order_by(Annotation.id)
                         .all()):
            ann_ids.append(aid)

    def _annotations_iter():
        for chunk in _chunks(image_ids):
            for a in (db.query(Annotation)
                        .filter(Annotation.image_id.in_(chunk))
                        .order_by(Annotation.id)
                        .yield_per(1000)):
                yield AnnotationEntry(
                    old_id=a.id, old_image_id=a.image_id,
                    x=a.x, y=a.y, w=a.w, h=a.h, label=a.label,
                    confidence=a.confidence,
                    is_frozen=bool(a.is_frozen),
                    behavior=a.behavior,
                    behavior_source=getattr(a, "behavior_source", None),
                    animal_id=a.animal_id,
                )

    def _keypoints_iter():
        for chunk in _chunks(ann_ids):
            for kp in (db.query(Keypoint)
                         .filter(Keypoint.annotation_id.in_(chunk))
                         .order_by(Keypoint.annotation_id, Keypoint.name)
                         .yield_per(1000)):
                yield KeypointEntry(
                    old_annotation_id=kp.annotation_id, name=kp.name,
                    x=kp.x, y=kp.y, visibility=kp.visibility,
                )

    tags: list[TagEntry] = []
    tag_ids: list[int] = []
    for t in db.query(Tag).filter(Tag.project_id == project_id).all():
        tags.append(TagEntry(old_id=t.id, name=t.name, color=t.color))
        tag_ids.append(t.id)
    image_tags: list[ImageTagEntry] = []
    for chunk in _chunks(image_ids):
        for it in (db.query(ImageTag)
                     .filter(ImageTag.image_id.in_(chunk)).all()):
            if it.tag_id in tag_ids:
                image_tags.append(ImageTagEntry(
                    old_image_id=it.image_id, old_tag_id=it.tag_id))

    versions: list[VersionEntry] = []
    if include_versions:
        for v in db.query(DatasetVersion).filter(
                DatasetVersion.project_id == project_id).all():
            versions.append(VersionEntry(
                hash=v.hash, created_at=_iso(v.created_at),
                image_count=int(v.image_count or 0),
                annotation_count=int(v.annotation_count or 0),
                keypoint_count=int(getattr(v, "keypoint_count", 0) or 0),
                behavior_count=int(getattr(v, "behavior_count", 0) or 0),
            ))

    blur: list[BlurRegionEntry] = []
    if include_blur_regions:
        for chunk in _chunks(image_ids):
            for r in (db.query(BlurRegion)
                        .filter(BlurRegion.image_id.in_(chunk)).all()):
                blur.append(BlurRegionEntry(
                    old_image_id=r.image_id, x=r.x, y=r.y, w=r.w, h=r.h))

    bvals: list[BehaviorValidationEntry] = []
    if include_behavior_validations:
        for chunk in _chunks(ann_ids):
            for bv in (db.query(BehaviorValidation)
                         .filter(BehaviorValidation.annotation_id.in_(chunk))
                         .all()):
                bvals.append(BehaviorValidationEntry(
                    old_annotation_id=bv.annotation_id,
                    auto_behavior=bv.auto_behavior,
                    true_behavior=bv.true_behavior,
                    is_match=int(bv.is_match or 0),
                    validated_at=_iso(bv.validated_at),
                    validated_by=bv.validated_by,
                ))

    streams: list[StreamEntry] = []
    if include_streams:
        for s in db.query(Stream).filter(
                Stream.project_id == project_id).all():
            _clean_url, _had_creds = _strip_stream_credentials(s.url or "")
            if _had_creds:
                warnings.append(
                    f"stream #{s.id}: credentials stripped from URL")
            streams.append(StreamEntry(
                old_id=s.id, url=_clean_url, name=s.name,
                capture_fps=float(getattr(s, "capture_fps", 1.0) or 1.0),
                is_active=bool(s.is_active),
            ))

    webhooks: list[WebhookEntry] = []
    if include_webhooks:
        for wh in db.query(Webhook).filter(
                Webhook.project_id == project_id).all():
            webhooks.append(WebhookEntry(
                old_id=wh.id, url=wh.url,
                event_type=wh.event_type,
                active=bool(wh.active),
            ))
        if webhooks:
            warnings.append(
                "webhook secret_key is NOT exported; re-enter after import")

    _counts_images = int(
        db.query(_func_bs.count(ImageModel.id))
          .filter(ImageModel.project_id == project_id,
                  ImageModel.is_deleted.is_(False))
          .scalar() or 0)
    _counts_annotations = int(
        db.query(_func_bs.count(Annotation.id))
          .join(ImageModel, Annotation.image_id == ImageModel.id)
          .filter(ImageModel.project_id == project_id,
                  ImageModel.is_deleted.is_(False))
          .scalar() or 0)
    _counts_keypoints = int(
        db.query(_func_bs.count(Keypoint.id))
          .join(Annotation, Keypoint.annotation_id == Annotation.id)
          .join(ImageModel, Annotation.image_id == ImageModel.id)
          .filter(ImageModel.project_id == project_id,
                  ImageModel.is_deleted.is_(False))
          .scalar() or 0)

    manifest = Manifest(
        app_version=APP_VERSION,
        created_at=utcnow().isoformat(),
        project={
            "name": project_entry.name,
            "object_class": project_entry.object_class,
            "object_class_source": project_entry.object_class_source,
        },
        counts=ManifestCounts(
            videos=len(videos), images=_counts_images,
            annotations=_counts_annotations, keypoints=_counts_keypoints,
            tags=len(tags), versions=len(versions),
            blur_regions=len(blur), behavior_validations=len(bvals),
            streams=len(streams), webhooks=len(webhooks),
        ),
        options=ManifestOptions(
            include_videos=include_videos,
            include_versions=include_versions,
            include_blur_regions=include_blur_regions,
            include_behavior_validations=include_behavior_validations,
            include_streams=include_streams,
            include_webhooks=include_webhooks,
        ),
        warnings=warnings,
    )

    total_files = _counts_images + (len(videos) if include_videos else 0)
    written_files = 0

    try:
        with zipfile.ZipFile(
            tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6
        ) as zf:
            zf.writestr("manifest.json",
                        manifest.model_dump_json(indent=2))
            zf.writestr("project.json",
                        project_entry.model_dump_json(indent=2))
            if schema_entry is not None:
                zf.writestr("keypoint_schema.json",
                            schema_entry.model_dump_json(indent=2))

            _write_json_stream(zf, "videos.json", videos)
            _write_json_stream(zf, "images.json", _images_iter())
            _write_json_stream(zf, "annotations.json", _annotations_iter())
            _write_json_stream(zf, "keypoints.json", _keypoints_iter())
            _write_json_stream(zf, "tags.json", tags)
            _write_json_stream(zf, "image_tags.json", image_tags)
            _write_json_stream(zf, "versions.json", versions)
            _write_json_stream(zf, "blur_regions.json", blur)
            _write_json_stream(zf, "behavior_validations.json", bvals)
            _write_json_stream(zf, "streams.json", streams)
            _write_json_stream(zf, "webhooks.json", webhooks)

            for e in _images_iter():
                src = (db.query(ImageModel)
                         .filter(ImageModel.id == e.old_id).first())
                if src and src.path and os.path.exists(src.path):
                    zf.write(src.path,
                             f"files/images/{e.old_id}{e.file_ext}")
                written_files += 1
                if progress_cb and written_files % 50 == 0:
                    progress_cb("files", written_files, total_files)

            if include_videos:
                for v in db.query(Video).filter(
                        Video.project_id == project_id,
                        Video.is_deleted.is_(False)).all():
                    ext = _ext_from_path(v.path, ".mp4")
                    if v.path and os.path.exists(v.path):
                        zf.write(v.path, f"files/videos/{v.id}{ext}")
                    written_files += 1
                    if progress_cb:
                        progress_cb("files", written_files, total_files)

        size = os.path.getsize(tmp_path)
        if size > _cfg.BACKUP_MAX_BYTES:
            os.remove(tmp_path)
            raise RuntimeError(f"Backup too large: {size} bytes")
        os.replace(tmp_path, out_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise

    return {
        "status": "ok",
        "zip_path": out_path,
        "zip_size": os.path.getsize(out_path),
        "project_id": project_id,
        "counts": manifest.counts.model_dump(),
        "warnings": warnings,
    }


import shutil

from fastapi import HTTPException
from services.file_service import (
    sanitize_display_name, validate_user_filename,
)


def _parse_dt(s):
    # Локальный хелпер: один use case (разбор ISO из архива).
    # Второй use case — вынести в общий модуль.
    if not s:
        return None
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(s.replace("Z", ""))
    except Exception:
        return None


def _safe_import_filename(
    raw_filename, old_id: int, file_ext: str,
    warnings: list,
) -> str:
    """Валидирует имя из архива. Невалидное → {old_id}{ext} + warning."""
    fallback = f"{old_id}{file_ext}"
    if not raw_filename:
        return fallback
    try:
        validate_user_filename(raw_filename)
    except HTTPException:
        warnings.append(
            f"image {old_id}: invalid filename {raw_filename!r}, replaced")
        return fallback
    safe = sanitize_display_name(raw_filename, fallback=fallback)
    return safe or fallback


def import_full_project(
    db: Session, zip_path: str, *,
    new_project_name=None,
    progress_cb=None,
) -> dict:
    import tempfile, zipfile
    from services.backup_validate import validate_archive
    from services.zip_import_service import _safe_extract_zip
    from services.image_service import _queue_thumb
    from config import VIDEO_DIR, UPLOAD_DIR

    tmp_dir = tempfile.mkdtemp(prefix="pdb_import_full_")
    copied_files: list = []
    new_pid = None

    try:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                _safe_extract_zip(zf, tmp_dir)
        except zipfile.BadZipFile:
            raise ValueError("Not a valid zip archive")

        v = validate_archive(tmp_dir)
        if v["errors"]:
            raise ValueError("; ".join(v["errors"][:5]))
        parsed = v["parsed"]
        warnings = list(v["warnings"])

        project_entry = parsed["project"]
        videos = parsed["videos"]
        images = parsed["images"]
        annotations = parsed["annotations"]
        keypoints = parsed["keypoints"]
        tags = parsed["tags"]
        image_tags = parsed["image_tags"]
        versions = parsed["versions"]
        blur = parsed["blur"]
        bvals = parsed["bvals"]
        streams = parsed.get("streams", [])
        webhooks = parsed.get("webhooks", [])

        base_name = new_project_name or f"{project_entry.name} (imported)"
        name = base_name
        suffix = 1
        while db.query(Project).filter(Project.name == name).first():
            suffix += 1
            name = f"{base_name} #{suffix}"

        new_project = Project(
            name=name,
            created_at=utcnow(),
            is_deleted=False,
            object_class=project_entry.object_class,
            object_class_source=project_entry.object_class_source,
            data_retention_days=project_entry.data_retention_days,
            trash_ttl_days_override=project_entry.trash_ttl_days_override,
            thumbnail_size=project_entry.thumbnail_size,
            default_zoom=project_entry.default_zoom,
            random_seed=project_entry.random_seed,
            auto_blur_enabled=project_entry.auto_blur_enabled,
            auto_blur_classes=project_entry.auto_blur_classes,
        )
        db.add(new_project)
        db.flush()
        new_pid = new_project.id

        schema_path = os.path.join(tmp_dir, "keypoint_schema.json")
        if os.path.exists(schema_path):
            try:
                with open(schema_path, encoding="utf-8") as f:
                    sk = json.load(f)
                schema_list = sk.get("schema_list") if isinstance(sk, dict) else None
                if schema_list:
                    db.add(ProjectKeypointSchema(
                        project_id=new_pid,
                        schema_json=json.dumps(schema_list, ensure_ascii=False),
                    ))
            except Exception:
                warnings.append("failed to restore keypoint_schema")

        video_map: dict = {}
        for vv in videos:
            ext = ".mp4"
            base = os.path.join(tmp_dir, "files", "videos")
            if os.path.isdir(base):
                for fname in os.listdir(base):
                    if fname.startswith(f"{vv.old_id}."):
                        ext = os.path.splitext(fname)[1].lower()
                        break
            src = os.path.join(tmp_dir, "files", "videos",
                               f"{vv.old_id}{ext}")
            new_path = os.path.join(VIDEO_DIR, f"{uuid.uuid4().hex}{ext}")
            if os.path.exists(src):
                shutil.copyfile(src, new_path)
                copied_files.append(new_path)
            else:
                warnings.append(
                    f"video {vv.old_id} file missing; created without file")
                new_path = ""
            nv = Video(
                project_id=new_pid, filename=vv.filename, path=new_path,
                fps=vv.fps, frame_count=vv.frame_count,
                duration_sec=vv.duration_sec, extract_fps=vv.extract_fps,
                images_count=vv.images_count,
                created_at=_parse_dt(vv.created_at) or utcnow(),
                is_deleted=False,
            )
            db.add(nv); db.flush()
            video_map[vv.old_id] = nv.id

        image_map: dict = {}
        for img in images:
            src = os.path.join(tmp_dir, "files", "images",
                               f"{img.old_id}{img.file_ext}")
            new_name = f"{uuid.uuid4().hex}{img.file_ext}"
            new_path = os.path.join(UPLOAD_DIR, new_name)
            shutil.copyfile(src, new_path)
            copied_files.append(new_path)

            safe_filename = _safe_import_filename(
                img.filename, img.old_id, img.file_ext, warnings)

            assigned_id = None
            if img.assigned_to_username:
                u = db.query(User).filter(
                    User.username == img.assigned_to_username).first()
                if u: assigned_id = u.id
                else: warnings.append(
                    f"user {img.assigned_to_username!r} not found")
            reviewed_id = None
            if img.reviewed_by_username:
                u = db.query(User).filter(
                    User.username == img.reviewed_by_username).first()
                if u: reviewed_id = u.id

            nim = ImageModel(
                project_id=new_pid, filename=safe_filename, path=new_path,
                width=img.width, height=img.height,
                original_width=img.original_width,
                original_height=img.original_height,
                is_hard=img.is_hard,
                is_stream_frame=img.is_stream_frame,
                phash=img.phash,
                video_id=video_map.get(img.old_video_id)
                          if img.old_video_id else None,
                frame_index=img.frame_index,
                timestamp_sec=img.timestamp_sec,
                created_at=_parse_dt(img.created_at) or utcnow(),
                file_size=img.file_size or os.path.getsize(new_path),
                revision=img.revision or 1,
                review_status=img.review_status or "unassigned",
                assigned_to=assigned_id,
                reviewed_by=reviewed_id,
                review_comment=img.review_comment,
                reviewed_at=_parse_dt(img.reviewed_at),
                is_deleted=False,
            )
            db.add(nim); db.flush()
            image_map[img.old_id] = nim.id
            from typing import cast as _cast_thumb_typing
            _queue_thumb(_cast_thumb_typing(int, nim.id),
                         _cast_thumb_typing(str, nim.path))

        ann_map: dict = {}
        for a in annotations:
            na = Annotation(
                image_id=image_map[a.old_image_id],
                x=a.x, y=a.y, w=a.w, h=a.h, label=a.label,
                confidence=a.confidence,
                is_frozen=a.is_frozen,
                behavior=a.behavior,
                behavior_source=a.behavior_source,
                animal_id=a.animal_id,
            )
            db.add(na); db.flush()
            ann_map[a.old_id] = na.id

        for kp in keypoints:
            db.add(Keypoint(
                annotation_id=ann_map[kp.old_annotation_id],
                name=kp.name, x=kp.x, y=kp.y, visibility=kp.visibility,
            ))

        tag_map: dict = {}
        for t in tags:
            nt = Tag(project_id=new_pid, name=t.name, color=t.color)
            db.add(nt); db.flush()
            tag_map[t.old_id] = nt.id

        for it in image_tags:
            if it.old_image_id in image_map and it.old_tag_id in tag_map:
                db.add(ImageTag(
                    image_id=image_map[it.old_image_id],
                    tag_id=tag_map[it.old_tag_id],
                ))

        for vv in versions:
            db.add(DatasetVersion(
                project_id=new_pid, hash=vv.hash,
                created_at=_parse_dt(vv.created_at) or utcnow(),
                image_count=vv.image_count,
                annotation_count=vv.annotation_count,
                keypoint_count=vv.keypoint_count,
                behavior_count=vv.behavior_count,
            ))

        for b in blur:
            if b.old_image_id in image_map:
                db.add(BlurRegion(
                    image_id=image_map[b.old_image_id],
                    x=b.x, y=b.y, w=b.w, h=b.h,
                ))

        for bv in bvals:
            if bv.old_annotation_id in ann_map:
                db.add(BehaviorValidation(
                    annotation_id=ann_map[bv.old_annotation_id],
                    project_id=new_pid,
                    auto_behavior=bv.auto_behavior,
                    true_behavior=bv.true_behavior,
                    is_match=bv.is_match,
                    validated_at=_parse_dt(bv.validated_at),
                    validated_by=bv.validated_by,
                ))

        # Streams: is_active=False, worker не стартует. Иначе импорт
        # немедленно начнёт подключаться к чужому RTSP.
        for s in streams:
            db.add(Stream(
                project_id=new_pid,
                url=s.url,
                name=s.name,
                is_active=False,
                capture_fps=s.capture_fps or 1.0,
            ))
        if streams:
            warnings.append(
                f"{len(streams)} stream(s) imported as inactive; "
                f"start manually after verifying URLs")

        # Webhooks: secret_key=None — секреты не переносятся.
        for wh in webhooks:
            db.add(Webhook(
                project_id=new_pid,
                url=wh.url,
                event_type=wh.event_type,
                active=bool(wh.active),
                secret_key=None,
                created_at=utcnow(),
            ))
        if webhooks:
            warnings.append(
                f"{len(webhooks)} webhook(s) imported without secret_key; "
                f"re-enter secrets manually")

        db.commit()
    except Exception:
        db.rollback()
        for p in copied_files:
            try: os.remove(p)
            except OSError: pass
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        from services.image_service import (
            _invalidate_phash_index, _invalidate_stats_cache,
        )
        from typing import cast as _cast_inv_typing
        if new_pid is not None:
            _invalidate_phash_index(_cast_inv_typing(int, new_pid))
            _invalidate_stats_cache(_cast_inv_typing(int, new_pid))
    except Exception:
        pass

    log_status("success", "backup", f"Full import: project #{new_pid}")
    return {
        "status": "ok",
        "project_id": new_pid,
        "counts": {
            "videos": len(videos), "images": len(images),
            "annotations": len(annotations), "keypoints": len(keypoints),
            "tags": len(tags), "versions": len(versions),
            "blur_regions": len(blur),
            "behavior_validations": len(bvals),
            "streams": len(streams),
            "webhooks": len(webhooks),
        },
        "warnings": warnings,
    }
