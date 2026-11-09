import os
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Depends, Body, Form
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from services.auth_service import get_current_user, require_permission
# [STAGE-SEC1:imports]
from services.project_access import (
    check_project_access, check_image_access,
)

# [PATCH:RBAC_IMPORT]
from models import Project, ImageModel, Annotation, Keypoint
from schemas import AutolabelIn, BatchAutolabelIn, SamPredictIn, PoseAutolabelIn, PredictBehaviorIn
from logger import log_status
from services.rate_limiter import _limiter_autolabel, _rate_limit
from services.behavior_service import predict_behavior_from_keypoints  # [STAGE1-A:behavior-audit-import]
from services.ml_service import (
    get_active_model_path, get_active_pose_model_path,
    _get_yolo_model, _autolabel_image_with_model,
    _apply_pose_detection_to_anns, _read_model_class_names, _resolve_target_class_ids,
)
from services.sam_service import (
    get_sam_model_name, _get_sam_model, _run_sam_predict, _clear_sam_cache,
    _SAM_CACHE, VALID_SAM_MODELS,
)
from config import SETTING_SAM_MODEL
from services.errors import _safe_error_message

router = APIRouter()

@router.get("/api/object_classes")
def object_classes(db: Session = Depends(get_db)):
    model_path = get_active_model_path(db)
    if not model_path: return {"source": "empty", "classes": [], "active_model": None}
    try:
        model = _get_yolo_model(model_path)
    except Exception as e:
        return {"source": "empty", "classes": [], "active_model": None, "error": str(e)}
    names = _read_model_class_names(model)
    return {"source": "model" if names else "empty", "classes": names, "active_model": os.path.basename(model_path)}

@router.post("/api/images/{image_id}/autolabel", dependencies=[Depends(require_permission("model.inference"))])
def autolabel(image_id: int, payload: AutolabelIn = Body(default_factory=AutolabelIn), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    # [STAGE-SEC1]:check:autolabel
    check_image_access(db, image_id, user)
    _rate_limit(_limiter_autolabel, "local", {"key": "error.rateLimitedAutolabel", "fallback": "Слишком много авторазметок. Подожди минуту."})
    model_path = get_active_model_path(db)
    if not model_path: raise HTTPException(501, {"key": "error.noModel", "fallback": "Активная модель не найдена"})
    try:
        model = _get_yolo_model(model_path)
    except Exception as e:
        raise HTTPException(500, {"key": "error.modelLoadFailed", "fallback": f"Ошибка загрузки модели: {e}", "params": {"err": _safe_error_message(e)}})
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    project = db.query(Project).filter(Project.id == img.project_id).first()
    if not project: raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    try:
        return _autolabel_image_with_model(db, img, model, project, tta=bool(payload.tta), mode=payload.mode)
    except ValueError as e:
        raise HTTPException(422, str(e))

@router.post("/api/images/{image_id}/autolabel_pose")
def autolabel_pose(image_id: int, payload: PoseAutolabelIn = Body(default_factory=PoseAutolabelIn), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    # [STAGE-SEC1]:check:autolabel_pose
    check_image_access(db, image_id, user)
    _rate_limit(_limiter_autolabel, "autolabel_pose", {"key": "error.rateLimitedAutolabel", "fallback": "Слишком много авторазметок."})
    from services.ml_service import get_active_pose_model_path
    model_path = get_active_pose_model_path(db)
    if not model_path: raise HTTPException(400, {"key": "error.poseModelNotFound", "fallback": "Нет pose-модели. Обучи её или положи yolov8n-pose.pt в папку models/."})
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    try:
        model = _get_yolo_model(model_path)
    except Exception as e:
        raise HTTPException(500, {"key": "error.poseLoadFailed", "fallback": f"Не удалось загрузить pose-модель: {e}", "params": {"err": _safe_error_message(e)}})
    try:
        results = model(img.path, conf=float(payload.conf), verbose=False)
    except Exception as e:
        raise HTTPException(500, {"key": "error.modelInferenceFailed", "fallback": f"Модель не смогла обработать: {e}", "params": {"err": _safe_error_message(e)}})
    summary = _apply_pose_detection_to_anns(db, img, results, only_empty=bool(payload.only_empty), iou_threshold=float(payload.iou_threshold))
    summary["model"] = os.path.basename(model_path)
    log_status("info", "autolabel", f"Pose-разметка image={img.id}: рамок {summary['saved_annotations']}, точек {summary['saved_keypoints']}, пропущено {summary['skipped_existing']}")
    return summary

@router.get("/api/sam/status")
def sam_status(db: Session = Depends(get_db)):
    name = get_sam_model_name(db)
    return {"model": name, "loaded": _SAM_CACHE.get(name) is not None, "available_models": list(VALID_SAM_MODELS)}

@router.post("/api/sam/set_model")
def sam_set_model(name: str = Form(...), db: Session = Depends(get_db)):
    if name not in VALID_SAM_MODELS: raise HTTPException(400, {"key": "error.samInvalidModel", "fallback": "Недопустимая SAM-модель"})
    from models import Setting
    from database import SessionLocal
    row = db.query(Setting).filter(Setting.key == SETTING_SAM_MODEL).first()
    if row: row.value = name
    else: db.add(Setting(key=SETTING_SAM_MODEL, value=name))
    db.commit()
    _clear_sam_cache()
    log_status("info", "model", f"SAM-модель: {name}")
    return {"model": name}

@router.post("/api/images/{image_id}/sam_predict", dependencies=[Depends(require_permission("model.inference"))])
def sam_predict(image_id: int, payload: SamPredictIn, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    # [STAGE-SEC1]:check:sam_predict
    check_image_access(db, image_id, user)
    _rate_limit(_limiter_autolabel, "sam", "Слишком много SAM-запросов. Подожди минуту.")
    pts = payload.points or []
    if len(pts) < 1: raise HTTPException(400, {"key": "error.samNoPoints", "fallback": "Нужна хотя бы одна точка"})
    if len(pts) > 8: raise HTTPException(400, {"key": "error.samTooManyPoints", "fallback": "Максимум 8 точек"})
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    name = get_sam_model_name(db)
    try:
        model = _get_sam_model(name)
    except ImportError:
        raise HTTPException(501, {"key": "error.samUnavailable", "fallback": "ultralytics не установлен — SAM недоступен"})
    except Exception as e:
        raise HTTPException(500, {"key": "error.samLoadFailed", "fallback": f"SAM не загружен: {e}", "params": {"err": _safe_error_message(e)}})
    W, H = img.width or 640, img.height or 640
    points_px = [[float(p.x) * W, float(p.y) * H] for p in pts]
    labels = [1 if p.positive else 0 for p in pts]
    try:
        res = _run_sam_predict(model, img.path, points_px, labels)
    except Exception as e:
        raise HTTPException(500, {"key": "error.samPredictFailed", "fallback": f"SAM predict: {e}", "params": {"err": _safe_error_message(e)}})
    if not res: return {"found": False}
    x1, y1, x2, y2 = res["bbox_px"]
    return {"found": True, "bbox": {"x": max(0.0, min(1.0, x1 / W)), "y": max(0.0, min(1.0, y1 / H)), "w": max(0.0, min(1.0, (x2 - x1) / W)), "h": max(0.0, min(1.0, (y2 - y1) / H))}, "score": res["score"], "mask": res["mask_b64"], "model": name}


# [STAGE1-A:behavior-audit]
@router.post("/api/images/{image_id}/behavior_audit")
def behavior_audit(image_id: int, payload: PredictBehaviorIn = Body(default_factory=PredictBehaviorIn),
                   user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Сравнивает эвристику с ручной разметкой; возвращает согласие."""
    # [STAGE-SEC1]:check:behavior_audit
    check_image_access(db, image_id, user)
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    anns = db.query(Annotation).filter(Annotation.image_id == image_id).order_by(Annotation.id).all()
    rows = []
    agree = 0
    total = 0
    for a in anns:
        if not a.behavior:
            continue
        kps = [{"name": k.name, "x": k.x, "y": k.y, "visibility": k.visibility}
               for k in db.query(Keypoint).filter(Keypoint.annotation_id == a.id).all()]
        if not kps:
            continue
        bbox = {"x": a.x, "y": a.y, "w": a.w, "h": a.h}
        r = predict_behavior_from_keypoints(kps, motion=None, bbox=bbox, project_id=img.project_id, db=db)  # [PATCH:C13]  # [PATCH:C13-FIX]
        heuristic = r.get("behavior")
        human = a.behavior
        ok = (heuristic == human)
        total += 1
        if ok:
            agree += 1
        rows.append({"ann_id": a.id, "animal_id": a.animal_id,
                     "heuristic": heuristic, "human": human,
                     "agree": ok, "reason": r.get("reason")})
    return {"image_id": image_id, "total": total, "agree": agree,
            "agreement": (agree / total) if total else 0.0, "rows": rows}


@router.post("/api/projects/{project_id}/behavior/calibrate")
def run_calibration(project_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    # [STAGE-SEC1]:check:run_calibration
    check_project_access(db, project_id, user)
    from services.behavior_service import calibrate_behavior_thresholds
    return calibrate_behavior_thresholds(db, project_id)

@router.delete("/api/projects/{project_id}/behavior/calibrate")
def reset_calibration(project_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    # [STAGE-SEC1]:check:reset_calibration
    check_project_access(db, project_id, user)
    from models import Setting
    key = f"behavior_thresholds_{project_id}"
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        db.delete(row)
        db.commit()
    # [STAGE3:invalidate-thresholds-cache-call] сбрасываем кэш,
    # чтобы дефолты применились без ожидания TTL
    from services.behavior_service import invalidate_thresholds_cache
    invalidate_thresholds_cache(project_id)
    return {"status": "reset"}

@router.get("/api/projects/{project_id}/behavior/thresholds")
def get_behavior_thresholds(project_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    # [STAGE-SEC1]:check:get_behavior_thresholds
    check_project_access(db, project_id, user)
    from services.settings_service import get_setting
    from config import (BEHAVIOR_DRINK_NOSE_Y, BEHAVIOR_ACTIVE_DELTA,
                        BEHAVIOR_ACTIVE_DELTA_PER_FRAME, BEHAVIOR_ACTIVE_BBOX_RATIO)
    import json
    t_json = get_setting(db, f"behavior_thresholds_{project_id}", None)
    if t_json is None:
        t_json = get_setting(db, "behavior_thresholds_global", None)
    if t_json:
        return json.loads(t_json)
    return {
        "drink_thr": BEHAVIOR_DRINK_NOSE_Y,
        "active_delta": BEHAVIOR_ACTIVE_DELTA,
        "active_per_frame": BEHAVIOR_ACTIVE_DELTA_PER_FRAME,
        "active_bbox_ratio": BEHAVIOR_ACTIVE_BBOX_RATIO
    }

# --- Stage 3.11 (moved from app.py) ---

from pydantic import BaseModel as _PydB
from config import KEYPOINT_SCHEMA as _KP_SCHEMA
from config import get_keypoint_schema_for_project as _gk_schema
from logger import utcnow as _utc


@router.get("/api/keypoint_schema")
def get_keypoint_schema(project_id: Optional[int] = None,
                        db: Session = Depends(get_db)):
    _schema = _gk_schema(db, project_id) if project_id else _KP_SCHEMA
    return {
        "names": [{"name": n, "label_ru": ru, "label_en": en, "parent": p}
                  for (n, ru, en, p) in _schema],
        "edges": [[p, n] for (n, _ru, _en, p) in _schema if p],
        "project_id": project_id,
    }


@router.get("/api/images/{image_id}/keypoints_by_index")
def keypoints_by_index(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound",
                                 "fallback": "Image not found"})
    anns = (db.query(Annotation)
              .filter(Annotation.image_id == image_id)
              .order_by(Annotation.id).all())
    ann_ids = [a.id for a in anns]
    out = {}
    if not ann_ids:
        return out
    kp_rows = (db.query(Keypoint)
                 .filter(Keypoint.annotation_id.in_(ann_ids)).all())
    by_ann = defaultdict(list)
    for kp in kp_rows:
        by_ann[kp.annotation_id].append({"name": kp.name, "x": kp.x,
                                         "y": kp.y, "visibility": kp.visibility})
    for i, a in enumerate(anns):
        out[str(i)] = by_ann.get(a.id, [])
    return out


@router.get("/api/projects/{project_id}/active_learning")
def active_learning_state(project_id: int,
                          user: dict = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    from models import Project as _P, ImageModel as _IM
    from sqlalchemy import func as _f
    from config import ACTIVE_LEARNING_NEW_THRESHOLD as _THR
    proj = db.query(_P).filter(_P.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    annotated_total = int(db.query(_f.count(_f.distinct(Annotation.image_id)))
                           .join(_IM, Annotation.image_id == _IM.id)
                           .filter(_IM.project_id == project_id,
                                   _IM.is_deleted.is_(False)).scalar() or 0)
    total_images = int(db.query(_f.count(_IM.id))
                        .filter(_IM.project_id == project_id,
                                _IM.is_deleted.is_(False)).scalar() or 0)
    last = _latest_train_run_for_project_local(db, project_id)
    if not last:
        return {"annotated_total": annotated_total, "total_images": total_images,
                "new_since_train": 0, "last_train": None,
                "show_suggestion": False, "reason": "no_previous_training",
                "threshold": _THR}
    last_count = int(last.get("annotated_count") or 0)
    new_since = max(0, annotated_total - last_count)
    show = new_since >= _THR and annotated_total > last_count
    return {"annotated_total": annotated_total, "total_images": total_images,
            "new_since_train": new_since,
            "last_train": {"run_id": last.get("run_id"),
                           "created_at": last.get("created_at"),
                           "model_name": last.get("model_name"),
                           "annotated_count": last_count,
                           "summary": last.get("summary") or {}},
            "show_suggestion": show,
            "reason": "enough_new_annotations" if show else "not_enough_new",
            "threshold": _THR}


def _latest_train_run_for_project_local(db, project_id: int):
    import os as _os
    from config import RUNS_DIR as _RD
    from routers.train import _read_run_metadata as _rrm
    if not _os.path.isdir(_RD):
        return None
    candidates = []
    for name in _os.listdir(_RD):
        if not name.startswith("train_"):
            continue
        meta_path = _os.path.join(_RD, name, "metadata.json")
        if not _os.path.exists(meta_path):
            continue
        try:
            mtime = _os.path.getmtime(meta_path)
            meta = _rrm(_RD, name, mtime)
            if meta is None:
                continue
            if int(meta.get("project_id", 0)) == project_id:
                candidates.append((meta.get("created_at", ""), meta))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


@router.get("/api/projects/{project_id}/skeletons_count")
def skeletons_count(project_id: int,
                    user: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    from services.ml_service import _count_annotations_with_skeleton as _cnt
    n = _cnt(db, project_id)
    return {"count": n, "min_required": 30}


class ValidateBehaviorIn(_PydB):
    image_id: int
    true_behavior: str
    annotation_id: Optional[int] = None
    validated_by: Optional[str] = None


_VALID_BEHAVIORS = {"eat", "walk", "lie", "drink", "stand", "active"}


@router.post("/api/projects/{project_id}/validate_behavior")
def validate_behavior(project_id: int, payload: ValidateBehaviorIn,
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    from models import BehaviorValidation as _BV
    norm = (payload.true_behavior or "").strip().lower()
    if norm not in _VALID_BEHAVIORS:
        raise HTTPException(400, f"true_behavior must be one of: {sorted(_VALID_BEHAVIORS)}")
    proj = db.query(Project).filter(Project.id == project_id,
                                     Project.is_deleted.is_(False)).first()
    if not proj:
        raise HTTPException(404, "Project not found")
    img = (db.query(ImageModel)
             .filter(ImageModel.id == payload.image_id,
                     ImageModel.project_id == project_id,
                     ImageModel.is_deleted.is_(False)).first())
    if not img:
        raise HTTPException(404, "Image not found in this project")
    q = db.query(Annotation).filter(Annotation.image_id == img.id)
    if payload.annotation_id is not None:
        q = q.filter(Annotation.id == payload.annotation_id)
    anns = q.order_by(Annotation.id).all()
    if not anns:
        raise HTTPException(404, "No annotations on image")
    details, matched_any = [], False
    for a in anns:
        auto = (a.behavior or "").strip().lower()
        if not auto:
            continue
        is_match = (auto == norm)
        if is_match:
            matched_any = True
        db.add(_BV(annotation_id=a.id, project_id=project_id,
                   auto_behavior=auto, true_behavior=norm,
                   is_match=1 if is_match else 0,
                   validated_at=_utc(), validated_by=payload.validated_by))
        details.append({"annotation_id": a.id, "auto_behavior": auto,
                        "is_match": is_match})
    if not details:
        raise HTTPException(400, "No annotations with behavior label on this image")
    db.commit()
    return {"is_match": matched_any,
            "auto_behavior": details[0]["auto_behavior"],
            "true_behavior": norm,
            "matched_count": sum(1 for d in details if d["is_match"]),
            "total": len(details), "details": details}


@router.get("/api/projects/{project_id}/agreement_score")
def agreement_score(project_id: int,
                    user: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    from models import BehaviorValidation as _BV
    proj = db.query(Project).filter(Project.id == project_id,
                                     Project.is_deleted.is_(False)).first()
    if not proj:
        raise HTTPException(404, "Project not found")
    rows = db.query(_BV).filter(_BV.project_id == project_id).all()
    n = len(rows)
    if n == 0:
        return {"project_id": project_id, "total": 0, "matches": 0,
                "agreement": None, "kappa": None,
                "reason": "no_validations_yet"}
    matches = sum(1 for r in rows if int(r.is_match or 0) == 1)
    p_o = matches / n
    classes = set()
    for r in rows:
        if r.auto_behavior:
            classes.add(r.auto_behavior)
        if r.true_behavior:
            classes.add(r.true_behavior)
    auto_counts = {c: 0 for c in classes}
    true_counts = {c: 0 for c in classes}
    for r in rows:
        if r.auto_behavior in auto_counts:
            auto_counts[r.auto_behavior] += 1
        if r.true_behavior in true_counts:
            true_counts[r.true_behavior] += 1
    p_e = sum((auto_counts[c] / n) * (true_counts[c] / n) for c in classes)
    kappa = None
    if p_e < 1.0:
        kappa = (p_o - p_e) / (1.0 - p_e)
    return {"project_id": project_id, "total": n, "matches": matches,
            "agreement": round(p_o, 4),
            "kappa": round(kappa, 4) if kappa is not None else None,
            "by_class": {c: {"auto": auto_counts[c], "true": true_counts[c]}
                         for c in sorted(classes)}}
