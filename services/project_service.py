import os
import logging
from database import SessionLocal, DB_ENGINE
from models import (
    Project, ImageModel, Annotation, Tag, ImageTag, Video, Keypoint,
    Webhook, DatasetVersion, Stream, ProjectKeypointSchema,
    UserProjectAccess, BehaviorValidation, ImageLock,  # [PATCH:STAGE2-C27]
)
from logger import log_status
from services.image_service import _remove_thumb, _remove_file_safe
from sqlalchemy import func

log = logging.getLogger("db")

def _purge_projects(db, project_ids: list) -> int:
    if not project_ids:
        return 0
    video_rows = db.query(Video.path).filter(Video.project_id.in_(project_ids)).all()
    video_paths = [r.path for r in video_rows]

    imgs = db.query(ImageModel.id, ImageModel.path).filter(
        ImageModel.project_id.in_(project_ids)
    ).all()
    img_ids = [im.id for im in imgs]
    img_paths = [im.path for im in imgs]
    tag_ids = [t.id for t in db.query(Tag.id).filter(Tag.project_id.in_(project_ids)).all()]

    # [PATCH:STAGE2-C27-delete-fk] Удаляем строки в таблицах с FK на projects,
    # которые не покрыты каскадом (SQLite/MySQL/PG): без этого
    # Project DELETE падает с IntegrityError на реальных проектах.
    db.query(BehaviorValidation).filter(
        BehaviorValidation.project_id.in_(project_ids)
    ).delete(synchronize_session=False)
    db.query(Webhook).filter(
        Webhook.project_id.in_(project_ids)
    ).delete(synchronize_session=False)
    db.query(DatasetVersion).filter(
        DatasetVersion.project_id.in_(project_ids)
    ).delete(synchronize_session=False)
    db.query(Stream).filter(
        Stream.project_id.in_(project_ids)
    ).delete(synchronize_session=False)
    db.query(ProjectKeypointSchema).filter(
        ProjectKeypointSchema.project_id.in_(project_ids)
    ).delete(synchronize_session=False)
    db.query(UserProjectAccess).filter(
        UserProjectAccess.project_id.in_(project_ids)
    ).delete(synchronize_session=False)
    # ImageLock через image_id, чанками по 500 (лимит SQLite 999)
    for _c27_i in range(0, len(img_ids), 500):
        _c27_chunk = img_ids[_c27_i:_c27_i + 500]
        db.query(ImageLock).filter(
            ImageLock.image_id.in_(_c27_chunk)
        ).delete(synchronize_session=False)


    # [PATCH:STAGE3_PURGE_CHUNKED]
    _all_ann_ids = []
    for _i in range(0, len(img_ids), 500):
        _c = img_ids[_i:_i + 500]
        for row in db.query(Annotation.id).filter(Annotation.image_id.in_(_c)).all():
            _all_ann_ids.append(row.id)
    for _i in range(0, len(_all_ann_ids), 500):
        _c = _all_ann_ids[_i:_i + 500]
        db.query(Keypoint).filter(Keypoint.annotation_id.in_(_c)).delete(synchronize_session=False)
    for _i in range(0, len(img_ids), 500):
        _c = img_ids[_i:_i + 500]
        db.query(Annotation).filter(Annotation.image_id.in_(_c)).delete(synchronize_session=False)
        db.query(ImageTag).filter(ImageTag.image_id.in_(_c)).delete(synchronize_session=False)
    # [/PATCH:STAGE3_PURGE_CHUNKED]
    if tag_ids:
        db.query(ImageTag).filter(ImageTag.tag_id.in_(tag_ids)).delete(synchronize_session=False)

    db.query(ImageModel).filter(ImageModel.project_id.in_(project_ids)).delete(synchronize_session=False)
    db.query(Video).filter(Video.project_id.in_(project_ids)).delete(synchronize_session=False)
    db.query(Tag).filter(Tag.project_id.in_(project_ids)).delete(synchronize_session=False)
    db.query(Project).filter(Project.id.in_(project_ids)).delete(synchronize_session=False)
    db.commit()

    for p in img_paths:
        _remove_file_safe(p)
    for iid in img_ids:
        _remove_thumb(iid)
    for vp in video_paths:
        _remove_file_safe(vp)

    log_status("warning", "trash", f"Полностью удалено проектов: {len(project_ids)}, файлов: {len(img_paths)}")
    return len(project_ids)
