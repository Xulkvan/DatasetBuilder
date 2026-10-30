# [PATCH:STAGE4_MOTION_SERVICE]
"""[STAGE4] Motion service — вынесено из app.py для разрыва цикла app↔pipeline."""
from __future__ import annotations

from collections import defaultdict

from models import ImageModel, Annotation, Keypoint
from services.image_service import _iou_xywh
from services.behavior_service import _get_stable_center


def _check_motion(db, image_id: int, animal_id: int, max_frames_back: int = 10):
    try:
        aid = int(animal_id)
    except (TypeError, ValueError):
        return None
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img or img.video_id is None or img.frame_index is None:
        return None
    cur_ann = db.query(Annotation).filter(Annotation.image_id == image_id,
                                          Annotation.animal_id == aid).first()
    if not cur_ann:
        return None
    cur_center, cur_type = _get_stable_center(
        cur_ann,
        db.query(Keypoint).filter(Keypoint.annotation_id == cur_ann.id).all())
    prev = (db.query(ImageModel, Annotation)
              .join(Annotation, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.video_id == img.video_id,
                      ImageModel.is_deleted.is_(False),
                      ImageModel.frame_index < img.frame_index,
                      ImageModel.frame_index >= img.frame_index - max_frames_back,
                      Annotation.animal_id == aid)
              .order_by(ImageModel.frame_index.desc()).first())
    if not prev:
        return None
    prev_img, prev_ann = prev
    prev_center, prev_type = _get_stable_center(
        prev_ann,
        db.query(Keypoint).filter(Keypoint.annotation_id == prev_ann.id).all())
    dx = cur_center[0] - prev_center[0]
    dy = cur_center[1] - prev_center[1]
    delta = (dx * dx + dy * dy) ** 0.5
    _bbox_size = max(float(cur_ann.w or 0.0), float(cur_ann.h or 0.0), 1e-6)
    return {
        "delta": float(delta),
        "from": prev_center,
        "to": cur_center,
        "frame_gap": int(img.frame_index - prev_img.frame_index),
        "center_source": "keypoints" if cur_type == "keypoints" and prev_type == "keypoints" else "bbox",
        "bbox_moved_ratio": float(delta) / _bbox_size,
    }


def _check_motion_batch(db, image_id: int):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img or img.video_id is None or img.frame_index is None:
        return {}
    cur_anns = (db.query(Annotation).filter(Annotation.image_id == image_id)
                  .order_by(Annotation.id).all())
    if not cur_anns:
        return {}
    prev_imgs = (db.query(ImageModel)
                   .filter(ImageModel.video_id == img.video_id,
                           ImageModel.is_deleted.is_(False),
                           ImageModel.frame_index < img.frame_index)
                   .order_by(ImageModel.frame_index.desc())
                   .limit(2).all())
    prev_by_aid = {}
    prev_anns_map = {}
    for pi in prev_imgs:
        anns = db.query(Annotation).filter(Annotation.image_id == pi.id).all()
        prev_anns_map[pi.frame_index] = anns
        for a in anns:
            if a.animal_id is not None:
                aid = int(a.animal_id)
                if aid not in prev_by_aid:
                    prev_by_aid[aid] = (a, pi.frame_index)
    cur_kps_map = defaultdict(list)
    for k in db.query(Keypoint).filter(
            Keypoint.annotation_id.in_([a.id for a in cur_anns])).all():
        cur_kps_map[k.annotation_id].append(k)
    prev_kps_map = defaultdict(list)
    all_prev_ids = [a.id for pi in prev_imgs for a in prev_anns_map.get(pi.frame_index, [])]
    if all_prev_ids:
        for k in db.query(Keypoint).filter(
                Keypoint.annotation_id.in_(all_prev_ids)).all():
            prev_kps_map[k.annotation_id].append(k)
    out = {}
    for i, a in enumerate(cur_anns):
        if a.animal_id is None:
            continue
        aid = int(a.animal_id)
        cur_center, cur_type = _get_stable_center(a, cur_kps_map.get(a.id, []))
        prev_match = prev_src = prev_idx = None
        if aid in prev_by_aid:
            prev_match, prev_idx = prev_by_aid[aid]
            prev_src = "aid"
        elif prev_imgs:
            imm_prev_idx = prev_imgs[0].frame_index
            for p in prev_anns_map.get(imm_prev_idx, []):
                if p.animal_id is not None and p.animal_id != aid:
                    continue
                iou = _iou_xywh({"x": a.x, "y": a.y, "w": a.w, "h": a.h},
                                {"x": p.x, "y": p.y, "w": p.w, "h": p.h})
                if iou >= 0.10:
                    prev_match, prev_idx, prev_src = p, imm_prev_idx, "iou"
                    break
        if prev_match is None:
            out[str(i)] = {"found": False,
                           "reason": "no_prev_match" if prev_imgs else "no_prev_frame"}
            continue
        prev_center, prev_type = _get_stable_center(
            prev_match, prev_kps_map.get(prev_match.id, []))
        match_type = "keypoints" if (cur_type == "keypoints" and prev_type == "keypoints") else "bbox"
        dx = cur_center[0] - prev_center[0]
        dy = cur_center[1] - prev_center[1]
        delta = (dx * dx + dy * dy) ** 0.5
        frame_gap = int(img.frame_index - prev_idx)
        if frame_gap > 2:
            out[str(i)] = {"found": False, "reason": "gap_too_large"}
            continue
        _bbox_size = max(float(a.w or 0.0), float(a.h or 0.0), 1e-6)
        out[str(i)] = {
            "found": True, "delta": float(delta),
            "from": prev_center, "to": cur_center,
            "frame_gap": frame_gap, "match_source": prev_src,
            "center_source": match_type,
            "prev_animal_id": int(prev_match.animal_id) if prev_match.animal_id is not None else None,
            "prev_frame_index": int(prev_idx),
            "bbox_moved_ratio": float(delta) / _bbox_size,
        }
    return out
# [/PATCH:STAGE4_MOTION_SERVICE]
