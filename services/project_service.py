import os
import logging
from database import SessionLocal, DB_ENGINE
from models import Project, ImageModel, Annotation, Tag, ImageTag, Video
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

    if img_ids:
        db.query(Annotation).filter(Annotation.image_id.in_(img_ids)).delete(synchronize_session=False)
        db.query(ImageTag).filter(ImageTag.image_id.in_(img_ids)).delete(synchronize_session=False)
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
