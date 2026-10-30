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


# ============================================================================
# [STAGE2:dataset-diff] Сравнение двух версий датасета.
# ============================================================================
def calculate_dataset_diff(db: Session, project_id: int,
                           hash_v1: str, hash_v2: str) -> dict:
    """Сравнивает две DatasetVersion по image_count / annotation_count."""
    from models import DatasetVersion
    v1 = (db.query(DatasetVersion)
            .filter(DatasetVersion.project_id == project_id,
                    DatasetVersion.hash == hash_v1)
            .order_by(DatasetVersion.id.desc()).first())
    v2 = (db.query(DatasetVersion)
            .filter(DatasetVersion.project_id == project_id,
                    DatasetVersion.hash == hash_v2)
            .order_by(DatasetVersion.id.desc()).first())
    if not v1 or not v2:
        return {"error": "version_not_found",
                "hash1_found": bool(v1), "hash2_found": bool(v2)}
    images_added = max(0, (v2.image_count or 0) - (v1.image_count or 0))
    images_removed = max(0, (v1.image_count or 0) - (v2.image_count or 0))
    annotations_added = max(0, (v2.annotation_count or 0) - (v1.annotation_count or 0))
    annotations_removed = max(0, (v1.annotation_count or 0) - (v2.annotation_count or 0))
    # [PATCH:STAGE4-C16-diff-kp-beh] keypoints/behaviors (getattr для старых БД)
    _v1_kp = int(getattr(v1, "keypoint_count", 0) or 0)
    _v2_kp = int(getattr(v2, "keypoint_count", 0) or 0)
    _v1_beh = int(getattr(v1, "behavior_count", 0) or 0)
    _v2_beh = int(getattr(v2, "behavior_count", 0) or 0)
    keypoints_added = max(0, _v2_kp - _v1_kp)
    keypoints_removed = max(0, _v1_kp - _v2_kp)
    behaviors_added = max(0, _v2_beh - _v1_beh)
    behaviors_removed = max(0, _v1_beh - _v2_beh)
    # [/PATCH:STAGE4-C16-diff-kp-beh]
    is_identical = (hash_v1 == hash_v2) or (
        images_added == 0 and images_removed == 0
        and annotations_added == 0 and annotations_removed == 0
        and keypoints_added == 0 and keypoints_removed == 0
        and behaviors_added == 0 and behaviors_removed == 0
    )
    return {
        "images_added": images_added,
        "images_removed": images_removed,
        "annotations_added": annotations_added,
        "annotations_removed": annotations_removed,
        "keypoints_added": keypoints_added,
        "keypoints_removed": keypoints_removed,
        "behaviors_added": behaviors_added,
        "behaviors_removed": behaviors_removed,
        "is_identical": bool(is_identical),
        "v1": {"hash": v1.hash, "image_count": v1.image_count or 0,
               "annotation_count": v1.annotation_count or 0,
               "created_at": v1.created_at.isoformat() if v1.created_at else None},
        "v2": {"hash": v2.hash, "image_count": v2.image_count or 0,
               "annotation_count": v2.annotation_count or 0,
               "created_at": v2.created_at.isoformat() if v2.created_at else None},
    }
# [/STAGE2:dataset-diff]
