"""Behavior prediction from keypoints and motion."""
import logging
from config import (
    BEHAVIOR_DRINK_NOSE_Y, BEHAVIOR_EAT_HEAD_TILT, BEHAVIOR_EAT_MID_OFFSET,
    BEHAVIOR_EAT_HEAD_BELOW_SPINE, BEHAVIOR_HOOF_OFFSET_STAND, BEHAVIOR_BODY_H_STAND,
    BEHAVIOR_WALK_DELTA, BEHAVIOR_ACTIVE_DELTA,
    BEHAVIOR_ACTIVE_DELTA_PER_FRAME, BEHAVIOR_ACTIVE_BBOX_RATIO,  # [STAGE6:test-fixes-2-imports]
)

log = logging.getLogger("db")

# [STAGE6:behavior-caches] Кэш pickle-классификатора и порогов
import threading as _threading
import time as _time_mod
_CLF_CACHE: dict = {}
_CLF_CACHE_LOCK = _threading.Lock()
_THRESHOLDS_CACHE: dict = {}
_THRESHOLDS_CACHE_LOCK = _threading.Lock()
_THRESHOLDS_CACHE_TTL = 60.0


def _load_classifier_cached(clf_path):
    """Кэш pickle по mtime — не читаем .pkl на каждый вызов."""
    import os as _os, pickle as _pickle
    if not _os.path.exists(clf_path):
        return None
    try:
        mtime = _os.path.getmtime(clf_path)
    except OSError:
        mtime = 0
    key = (clf_path, mtime)
    with _CLF_CACHE_LOCK:
        if key in _CLF_CACHE:
            return _CLF_CACHE[key]
    try:
        with open(clf_path, 'rb') as _f:
            clf = _pickle.load(_f)
    except Exception:
        return None
    with _CLF_CACHE_LOCK:
        for _k in [k for k in _CLF_CACHE if k[0] == clf_path]:
            del _CLF_CACHE[_k]
        _CLF_CACHE[key] = clf
    return clf


def _get_thresholds_cached(project_id):
    """Кэш порогов поведения с TTL 60с."""
    now = _time_mod.time()
    with _THRESHOLDS_CACHE_LOCK:
        hit = _THRESHOLDS_CACHE.get(project_id)
        if hit and (now - hit[0]) < _THRESHOLDS_CACHE_TTL:
            return hit[1]
    from database import SessionLocal as _SL
    from services.settings_service import get_setting as _gs
    db = _SL()
    try:
        t_json = None
        if project_id is not None:
            t_json = _gs(db, f'behavior_thresholds_{project_id}', None)
        if t_json is None:
            t_json = _gs(db, 'behavior_thresholds_global', None)
        import json as _json
        val = _json.loads(t_json) if t_json else None
    except Exception:
        val = None
    finally:
        db.close()
    with _THRESHOLDS_CACHE_LOCK:
        _THRESHOLDS_CACHE[project_id] = (now, val)
    return val


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
        thresholds = _get_thresholds_cached(project_id)
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

    # [FIX:v1341-backend] Priority: motion (walk/active) > classifier > heuristic.
    heuristic = _predict_behavior_from_keypoints_orig(
        keypoints, motion=motion, bbox=bbox, thresholds=_t)

    # Motion (walk/active) — эвристика не перебивается классификатором.
    if motion and heuristic.get("behavior") in ("walk", "active"):
        heuristic["source"] = "heuristic"
        if bbox is None:
            heuristic["deprecated"] = True
        _d = heuristic.setdefault("diag", {})
        if isinstance(_d, dict):
            _d["bbox_provided"] = bbox is not None
        return heuristic

    # Классификатор (per-project) — если уверенно предсказал.
    clf_pred = _try_classifier(project_id, keypoints, bbox, motion)
    if clf_pred is not None:
        # Если эвристика уверена сильнее — оставим её.
        if (heuristic.get("confidence", 0) or 0) >= 0.8 \
           and (clf_pred.get("confidence", 0) or 0) < 0.7:
            heuristic["source"] = "heuristic"
            return heuristic
        clf_pred["deprecated"] = bbox is None
        clf_pred["diag"] = {"bbox_provided": bbox is not None}
        return clf_pred

    # Fallback — эвристика.
    heuristic["source"] = "heuristic"
    if bbox is None:
        heuristic["deprecated"] = True
        heuristic["warning"] = "bbox not provided, aspect ratio may distort behavior"
    _diag = heuristic.setdefault("diag", {})
    if isinstance(_diag, dict):
        _diag["bbox_provided"] = bbox is not None
    return heuristic


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


# ============================================================================
# [STAGE3:behavior-classifier] RandomForest-классификатор поведения из скелета.
# ============================================================================
def _behavior_features(keypoints, bbox=None):
    """[FIX:v1341-backend] Числовой вектор признаков из keypoints.

    Точки НОРМАЛИЗУЮТСЯ относительно bbox (если передан), чтобы модель
    не зависела от абсолютных пропорций кадра. Если bbox не передан —
    используются абсолютные координаты (для обратной совместимости)."""
    pts = _kp_lookup(keypoints)
    if not pts:
        return None
    if bbox and bbox.get("w") and bbox.get("h"):
        _bx = float(bbox["x"]); _by = float(bbox["y"])
        _bw = float(bbox["w"]) or 1e-6
        _bh = float(bbox["h"]) or 1e-6
        def _norm(pt):
            return ((pt[0] - _bx) / _bw, (pt[1] - _by) / _bh)
    else:
        def _norm(pt):
            return pt
    names = ("nose", "head_top", "neck", "withers", "mid_spine", "hip",
             "tail_base", "hoof_FL", "hoof_FR", "hoof_RL", "hoof_RR")
    feats = []
    npts = {}
    for nm in names:
        if nm in pts:
            nx, ny = _norm(pts[nm])
            feats.extend([float(nx), float(ny)])
            npts[nm] = (nx, ny)
        else:
            feats.extend([-1.0, -1.0])
    if "nose" in npts and "withers" in npts:
        nx, ny = npts["nose"]; wx, wy = npts["withers"]
        feats.append(float(ny - wy))
        feats.append(((nx - wx) ** 2 + (ny - wy) ** 2) ** 0.5)
    else:
        feats.extend([0.0, 0.0])
    if "hoof_FL" in npts and "withers" in npts:
        feats.append(float(npts["hoof_FL"][1] - npts["withers"][1]))
    else:
        feats.append(0.0)
    return feats

def _clf_path(project_id):
    import os
    from config import MODEL_DIR
    return os.path.join(MODEL_DIR, f"behavior_clf_project_{project_id}.pkl")

def _clf_meta_path(project_id):
    import os
    from config import MODEL_DIR
    return os.path.join(MODEL_DIR, f"behavior_clf_project_{project_id}.meta.json")

def get_behavior_classifier_meta(project_id):
    """Метаданные обученного классификатора или None."""
    import os
    import json
    if project_id is None:
        return None
    mp = _clf_meta_path(project_id)
    cp = _clf_path(project_id)
    if not os.path.exists(cp):
        return None
    try:
        if os.path.exists(mp):
            with open(mp, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"project_id": project_id, "exists": True}

def _try_classifier(project_id, keypoints, bbox, motion=None):
    """Возвращает предсказание классификатора (>=0.6 proba) или None."""
    import os
    import pickle
    if project_id is None:
        return None
    clf_path = _clf_path(project_id)
    if not os.path.exists(clf_path):
        return None
    feat = _behavior_features(keypoints, bbox)
    if feat is None:
        return None
    try:
        clf = _load_classifier_cached(clf_path)
        if clf is None:
            return None
        proba = clf.predict_proba([feat])[0]
        classes = list(clf.classes_)
        idx = int(proba.argmax())
        pred = str(classes[idx])
        conf = float(proba[idx])
        if conf < 0.6:
            return None
        return {
            "behavior": pred,
            "confidence": conf,
            "reason": f"classifier proba={conf:.2f}",
            "source": "classifier",
            "motion": None,
            "received_names": sorted(
                [p.get("name", "") for p in (keypoints or [])
                 if isinstance(p, dict)]),
        }
    except Exception:
        return None


def train_behavior_classifier(db, project_id: int) -> dict:
    """Обучает RandomForestClassifier на размеченных behavior из БД.

    Сохраняет модель в models/behavior_clf.pkl. Требует >=20 примеров
    с размеченным поведением и видимыми keypoints.
    """
    import os as _os
    import pickle as _pickle
    from config import MODEL_DIR as _MODEL_DIR
    try:
        from sklearn.ensemble import RandomForestClassifier
    except ImportError:
        return {"error": "sklearn not installed (pip install scikit-learn)"}
    from models import Annotation, Keypoint, ImageModel
    rows = (db.query(Annotation)
              .join(ImageModel, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False),
                      Annotation.behavior.isnot(None))
              .all())
    X, y = [], []
    for a in rows:
        kps = [{"name": k.name, "x": k.x, "y": k.y,
                "visibility": k.visibility}
               for k in db.query(Keypoint)
                          .filter(Keypoint.annotation_id == a.id).all()]
        if not kps:
            continue
        feat = _behavior_features(kps,
                                  {"x": a.x, "y": a.y, "w": a.w, "h": a.h})
        if feat is None:
            continue
        X.append(feat)
        y.append(a.behavior)
    if len(X) < 20:
        return {"error": f"need >=20 annotated behaviors, got {len(X)}"}
    clf = RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1)
    clf.fit(X, y)
    _os.makedirs(_MODEL_DIR, exist_ok=True)
    # [FIX:v1341-backend] per-project .pkl + meta.json
    path = _os.path.join(_MODEL_DIR, f"behavior_clf_project_{project_id}.pkl")
    meta_path = _os.path.join(_MODEL_DIR, f"behavior_clf_project_{project_id}.meta.json")
    with open(path, "wb") as f:
        _pickle.dump(clf, f)
    try:
        import json as _json
        from logger import utcnow as _utcnow
        _proj = (db.query(Project)
                   .filter(Project.id == project_id).first())
        with open(meta_path, "w", encoding="utf-8") as mf:
            _json.dump({
                "project_id": project_id,
                "object_class": (_proj.object_class if _proj else None),
                "n_samples": len(X),
                "classes": [str(c) for c in clf.classes_],
                "trained_at": _utcnow().isoformat(),
            }, mf, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return {
        "trained": True,
        "n_samples": len(X),
        "classes": [str(c) for c in clf.classes_],
        "path": path,
    }
# [/STAGE3:behavior-classifier]
