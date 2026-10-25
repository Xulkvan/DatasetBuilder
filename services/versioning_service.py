"""[STAGE1:versioning] DVC-подобный хеш датасета."""
from __future__ import annotations

import hashlib
import logging
import os

from sqlalchemy.orm import Session

from models import ImageModel, Annotation, Keypoint

log = logging.getLogger("db")


def _file_md5(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                buf = f.read(1024 * 1024)
                if not buf:
                    break
                h.update(buf)
        return h.hexdigest()
    except OSError:
        return ""


def calculate_dataset_hash(db: Session, project_id: int) -> str:
    """SHA-256 по (image_id, file_size, md5, sorted bbox/animal_id/behavior/keypoints)."""
    h = hashlib.sha256()
    images = (db.query(ImageModel)
                .filter(ImageModel.project_id == project_id,
                        ImageModel.is_deleted.is_(False))
                .order_by(ImageModel.id).all())
    for img in images:
        md5 = _file_md5(img.path)
        h.update(f"{img.id}|{img.file_size or 0}|{md5}\n".encode("utf-8"))
        anns = (db.query(Annotation)
                  .filter(Annotation.image_id == img.id)
                  .order_by(Annotation.id).all())
        for a in anns:
            kps = (db.query(Keypoint)
                     .filter(Keypoint.annotation_id == a.id)
                     .order_by(Keypoint.name).all())
            kp_str = ";".join(
                f"{k.name},{round(k.x,6)},{round(k.y,6)},{round(k.visibility,3)}"
                for k in kps)
            h.update(
                f"{round(a.x,6)},{round(a.y,6)},{round(a.w,6)},{round(a.h,6)},"
                f"{a.animal_id},{a.behavior},{kp_str}\n".encode("utf-8"))
    return h.hexdigest()
