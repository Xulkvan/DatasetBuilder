"""Behavior prediction from keypoints and motion."""
import logging
from config import (
    BEHAVIOR_DRINK_NOSE_Y, BEHAVIOR_EAT_HEAD_TILT, BEHAVIOR_EAT_MID_OFFSET,
    BEHAVIOR_EAT_HEAD_BELOW_SPINE, BEHAVIOR_HOOF_OFFSET_STAND, BEHAVIOR_BODY_H_STAND,
    BEHAVIOR_WALK_DELTA, BEHAVIOR_ACTIVE_DELTA,
)

log = logging.getLogger("db")

def _kp_lookup(keypoints):
    out = {}
    for p in (keypoints or []):
        try:
            nm = str(p.get("name", "")).strip()
            vis = float(p.get("visibility", 1.0))
        except (TypeError, ValueError, AttributeError):
            continue
        if nm and vis >= 0.5:
            try:
                out[nm] = (float(p.get("x", 0)), float(p.get("y", 0)))
            except (TypeError, ValueError):
                continue
    return out

def _avg_y(pts, names):
    ys = [pts[n][1] for n in names if n in pts]
    return sum(ys) / len(ys) if ys else None

def _get_stable_center(ann, kps):
    stable_names = {'nose', 'withers', 'mid_spine', 'hip', 'neck'}
    valid = [k for k in kps if k.name in stable_names and (k.visibility or 1.0) >= 0.5]
    if len(valid) >= 2:
        cx = sum(k.x for k in valid) / len(valid)
        cy = sum(k.y for k in valid) / len(valid)
        return [round(cx, 5), round(cy, 5)], "keypoints"
    cx = ann.x + ann.w / 2
    cy = ann.y + ann.h / 2
    return [round(cx, 5), round(cy, 5)], "bbox"

def _predict_behavior_from_keypoints_orig(keypoints, motion=None, bbox=None, thresholds=None):  # [STAGE1-A:behavior-bbox-relative]
    pts = _kp_lookup(keypoints)
    thresholds = thresholds or {}
    # [STAGE1-A:behavior-bbox-relative]
    if bbox is not None:
        try:
            _bbox_y = float(bbox.get("y", 0.0))
            _bbox_h = float(bbox.get("h", 1.0)) or 1e-6
        except (TypeError, ValueError):
            _bbox_y, _bbox_h = 0.0, 1.0
        _drink_thr = _bbox_y + _bbox_h * 0.80
        _body_h_thr = _bbox_h * 0.60
    else:
        _drink_thr = BEHAVIOR_DRINK_NOSE_Y
        _body_h_thr = BEHAVIOR_BODY_H_STAND
    motion_block = None
    if motion:
        motion_block = {
            "delta": round(float(motion.get("delta", 0.0)), 4),
            "from": motion.get("from"),
            "to": motion.get("to"),
            "walk_threshold": BEHAVIOR_WALK_DELTA,
            "active_threshold": BEHAVIOR_ACTIVE_DELTA,
        }

    if not pts:
        return {"behavior": None, "confidence": 0.0,
                "reason": "no_visible_keypoints",
                "motion": motion_block,
                "received_names": sorted(pts.keys())}

    nose = pts.get("nose")
    head_top = pts.get("head_top")
    neck = pts.get("neck")
    spine_names = ("withers", "mid_spine", "hip", "tail_base")
    spine_ys = [pts[n][1] for n in spine_names if n in pts]
    spine_y = sum(spine_ys) / len(spine_ys) if spine_ys else None

    if nose is None or spine_y is None:
        missing = []
        if nose is None: missing.append("nose")
        if spine_y is None: missing.append("spine")
        return {"behavior": None, "confidence": 0.0,
                "reason": "need_" + "_and_".join(missing),
                "motion": motion_block,
                "received_names": sorted(pts.keys())}

    nose_y = nose[1]
    head_top_y = head_top[1] if head_top is not None else None
    head_ref_y = head_top_y if head_top_y is not None else (neck[1] if neck is not None else None)
    head_tilt = None
    if head_ref_y is not None:
        head_tilt = max(0.0, nose_y - head_ref_y)

    hooves_y = _avg_y(pts, ["hoof_FL", "hoof_FR", "hoof_RL", "hoof_RR"])
    visible_hooves = [n for n in ("hoof_FL", "hoof_FR", "hoof_RL", "hoof_RR") if n in pts]
    all_ys = [p[1] for p in pts.values()]
    body_h = max(all_ys) - min(all_ys) if all_ys else None

    diag = {
        "nose_y": round(nose_y, 3),
        "head_tilt": None if head_tilt is None else round(head_tilt, 3),
        "head_top_y": None if head_top_y is None else round(head_top_y, 3),
        "spine_y": round(spine_y, 3),
        "hooves_y": None if hooves_y is None else round(hooves_y, 3),
        "body_h": None if body_h is None else round(body_h, 3),
        "visible_hooves": len(visible_hooves),
    }


    if nose_y > _drink_thr:
        return {"behavior": "drink", "confidence": 0.8,
                "reason": "nose_y=%.2f > %.2f" % (nose_y, _drink_thr),
                "diag": diag, "motion": motion_block,
                "received_names": sorted(pts.keys())}

    eat_reasons = []
    if hooves_y is not None and len(visible_hooves) >= 2:
        eat_mid = (spine_y + hooves_y) / 2 + BEHAVIOR_EAT_MID_OFFSET
        diag["eat_mid"] = round(eat_mid, 3)
        if nose_y > eat_mid:
            eat_reasons.append("nose=%.2f > mid+off=%.2f" % (nose_y, eat_mid))
    if head_tilt is not None and head_tilt > BEHAVIOR_EAT_HEAD_TILT:
        eat_reasons.append("tilt=%.2f > %.2f" % (head_tilt, BEHAVIOR_EAT_HEAD_TILT))
    if head_top_y is not None and head_top_y > (spine_y + BEHAVIOR_EAT_HEAD_BELOW_SPINE):
        eat_reasons.append("head_top=%.2f > spine+%.2f=%.2f"
                           % (head_top_y, BEHAVIOR_EAT_HEAD_BELOW_SPINE,
                              spine_y + BEHAVIOR_EAT_HEAD_BELOW_SPINE))
    if eat_reasons:
        return {"behavior": "eat", "confidence": 0.78,
                "reason": " OR ".join(eat_reasons),
                "diag": diag, "motion": motion_block,
                "received_names": sorted(pts.keys())}

    # [STAGE1-FIX:behavior-priority]
    # [V13.1.0:active-smooth]
    _is_active = False
    if motion is not None:
        d = motion.get("delta", 0.0)
        fg = max(1, motion.get("frame_gap", 1))
        d_pf = d / fg
        b_ratio = motion.get("bbox_moved_ratio", 0.0)
        thr_d = thresholds.get("active_delta", BEHAVIOR_ACTIVE_DELTA)
        thr_pf = thresholds.get("active_per_frame", BEHAVIOR_ACTIVE_DELTA_PER_FRAME)
        thr_br = thresholds.get("active_bbox_ratio", BEHAVIOR_ACTIVE_BBOX_RATIO)
        if d > thr_d and d_pf > thr_pf and b_ratio > thr_br:
            _is_active = True

    if _is_active:
        return {"behavior": "active", "confidence": 0.75,
                "reason": "delta=%.3f > %.3f" % (motion["delta"], BEHAVIOR_ACTIVE_DELTA),
                "diag": diag, "motion": motion_block,
                "received_names": sorted(pts.keys())}

    if motion is not None and motion.get("delta", 0.0) > BEHAVIOR_WALK_DELTA:
        return {"behavior": "walk", "confidence": 0.7,
                "reason": "delta=%.3f > %.3f" % (motion["delta"], BEHAVIOR_WALK_DELTA),
                "diag": diag, "motion": motion_block,
                "received_names": sorted(pts.keys())}

    offset = None
    if hooves_y is not None and len(visible_hooves) >= 2:
        offset = hooves_y - spine_y
        diag["hoof_offset"] = round(offset, 3)

    if offset is not None:
        if offset >= BEHAVIOR_HOOF_OFFSET_STAND:
            return {"behavior": "stand", "confidence": 0.75,
                    "reason": "hoof_offset=%.2f >= %.2f" % (offset, BEHAVIOR_HOOF_OFFSET_STAND),
                    "diag": diag, "motion": motion_block,
                    "received_names": sorted(pts.keys())}
        if offset < 0.18:
            return {"behavior": "lie", "confidence": 0.75,
                    "reason": "hoof_offset=%.2f < 0.18" % offset,
                    "diag": diag, "motion": motion_block,
                    "received_names": sorted(pts.keys())}
        if body_h is not None and body_h >= _body_h_thr:
            return {"behavior": "stand", "confidence": 0.65,
                    "reason": "hoof_offset=%.2f borderline, body_h=%.2f" % (offset, body_h),
                    "diag": diag, "motion": motion_block,
                    "received_names": sorted(pts.keys())}
        return {"behavior": "lie", "confidence": 0.65,
                "reason": "hoof_offset=%.2f borderline" % offset,
                "diag": diag, "motion": motion_block,
                "received_names": sorted(pts.keys())}

    if body_h is not None:
        if body_h >= _body_h_thr:
            return {"behavior": "stand", "confidence": 0.4,
                    "reason": "no_hooves, body_h=%.2f" % body_h,
                    "diag": diag, "motion": motion_block,
                    "received_names": sorted(pts.keys())}
        if body_h < 0.30:
            return {"behavior": "lie", "confidence": 0.4,
                    "reason": "no_hooves, body_h=%.2f" % body_h,
                    "diag": diag, "motion": motion_block,
                    "received_names": sorted(pts.keys())}

    return {"behavior": None, "confidence": 0.0,
            "reason": "no_rule_matched",
            "diag": diag, "motion": motion_block,
            "received_names": sorted(pts.keys())}


# [STAGE1-A:behavior-bbox-relative] public wrapper
def predict_behavior_from_keypoints(keypoints, motion=None, bbox=None, thresholds=None, project_id=None):
    # [V13.1.0:calibrate]
    if thresholds is None:
        try:
            from database import SessionLocal
            from services.settings_service import get_setting
            from models import Project
            # В идеале передавать project_id, но для простоты берем глобальные настройки
            db = SessionLocal()
            t_json = None
            if project_id is not None:
                t_json = get_setting(db, f"behavior_thresholds_{project_id}", None)
            if t_json is None:
                t_json = get_setting(db, "behavior_thresholds_global", None)
            db.close()
            if t_json:
                import json
                thresholds = json.loads(t_json)
        except Exception:
            thresholds = None
    if thresholds:
        _t = thresholds
    else:
        from config import BEHAVIOR_DRINK_NOSE_Y, BEHAVIOR_ACTIVE_DELTA, BEHAVIOR_ACTIVE_DELTA_PER_FRAME, BEHAVIOR_ACTIVE_BBOX_RATIO
        _t = {
            "drink_thr": BEHAVIOR_DRINK_NOSE_Y,
            "active_delta": BEHAVIOR_ACTIVE_DELTA,
            "active_per_frame": BEHAVIOR_ACTIVE_DELTA_PER_FRAME,
            "active_bbox_ratio": BEHAVIOR_ACTIVE_BBOX_RATIO
        }

    result = _predict_behavior_from_keypoints_orig(keypoints, motion=motion, bbox=bbox, thresholds=_t)
    if bbox is None:
        result["deprecated"] = True
        result["warning"] = "bbox not provided, aspect ratio may distort behavior"
    _diag = result.setdefault("diag", {})
    if isinstance(_diag, dict):
        _diag["bbox_provided"] = bbox is not None
    return result


# [V13.1.0:calibrate-fn]
def calibrate_behavior_thresholds(db, project_id):
    """Grid search порогов для максимизации точности."""
    import itertools, json
    from models import Annotation, Keypoint, ImageModel, Setting
    anns = db.query(Annotation).join(ImageModel).filter(
        ImageModel.project_id == project_id,
        ImageModel.is_deleted.is_(False),
        Annotation.behavior.isnot(None)
    ).all()

    pairs = []
    for a in anns:
        kps = [{"name": k.name, "x": k.x, "y": k.y, "visibility": k.visibility}
               for k in db.query(Keypoint).filter(Keypoint.annotation_id == a.id).all()]
        if kps:
            pairs.append((kps, a.behavior, {"x": a.x, "y": a.y, "w": a.w, "h": a.h}))

    if len(pairs) < 10:
        return {"error": "Мало данных (нужно >= 10 размеченных поведений)"}

    grid_drink = [0.70, 0.75, 0.80, 0.85, 0.90]
    grid_active = [0.10, 0.15, 0.20, 0.25, 0.30]
    grid_per_frame = [0.02, 0.04, 0.06]
    best_acc = -1
    best_thr = {}

    for d, a_d, a_pf in itertools.product(grid_drink, grid_active, grid_per_frame):
        thr = {
            "drink_thr": d, "active_delta": a_d, "active_per_frame": a_pf,
            "active_bbox_ratio": 0.20
        }
        correct = 0
        for kps, human, bbox in pairs:
            r = _predict_behavior_from_keypoints_orig(kps, bbox=bbox, thresholds=thr)
            if r.get("behavior") == human:
                correct += 1
        acc = correct / len(pairs)
        if acc > best_acc:
            best_acc = acc
            best_thr = thr

    # Сохраняем
    json_val = json.dumps(best_thr)
    key = f"behavior_thresholds_{project_id}"
    row = db.query(Setting).filter(Setting.key == key).first()
    if row: row.value = json_val
    else: db.add(Setting(key=key, value=json_val))
    db.commit()

    return {"accuracy": best_acc, "n_pairs": len(pairs), "thresholds": best_thr}
