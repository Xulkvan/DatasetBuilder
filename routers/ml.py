import os
from fastapi import APIRouter, HTTPException, Depends, Body, Form
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
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

@router.post("/api/images/{image_id}/autolabel")
def autolabel(image_id: int, payload: AutolabelIn = Body(default_factory=AutolabelIn), db: Session = Depends(get_db)):
    _rate_limit(_limiter_autolabel, "local", {"key": "error.rateLimitedAutolabel", "fallback": "Слишком много авторазметок. Подожди минуту."})
    model_path = get_active_model_path(db)
    if not model_path: raise HTTPException(501, {"key": "error.noModel", "fallback": "Активная модель не найдена"})
    try:
        model = _get_yolo_model(model_path)
    except Exception as e:
        raise HTTPException(500, f"Ошибка загрузки модели: {e}")
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    project = db.query(Project).filter(Project.id == img.project_id).first()
    if not project: raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    try:
        return _autolabel_image_with_model(db, img, model, project, tta=bool(payload.tta), mode=payload.mode)
    except ValueError as e:
        raise HTTPException(422, str(e))

@router.post("/api/images/{image_id}/autolabel_pose")
def autolabel_pose(image_id: int, payload: PoseAutolabelIn = Body(default_factory=PoseAutolabelIn), db: Session = Depends(get_db)):
    _rate_limit(_limiter_autolabel, "autolabel_pose", {"key": "error.rateLimitedAutolabel", "fallback": "Слишком много авторазметок."})
    from services.ml_service import get_active_pose_model_path
    model_path = get_active_pose_model_path(db)
    if not model_path: raise HTTPException(400, "Нет pose-модели. Обучи её или положи yolov8n-pose.pt в папку models/.")
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    try:
        model = _get_yolo_model(model_path)
    except Exception as e:
        raise HTTPException(500, f"Не удалось загрузить pose-модель: {e}")
    try:
        results = model(img.path, conf=float(payload.conf), verbose=False)
    except Exception as e:
        raise HTTPException(500, f"Модель не смогла обработать: {e}")
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
    if name not in VALID_SAM_MODELS: raise HTTPException(400, "Недопустимая SAM-модель")
    from models import Setting
    from database import SessionLocal
    row = db.query(Setting).filter(Setting.key == SETTING_SAM_MODEL).first()
    if row: row.value = name
    else: db.add(Setting(key=SETTING_SAM_MODEL, value=name))
    db.commit()
    _clear_sam_cache()
    log_status("info", "model", f"SAM-модель: {name}")
    return {"model": name}

@router.post("/api/images/{image_id}/sam_predict")
def sam_predict(image_id: int, payload: SamPredictIn, db: Session = Depends(get_db)):
    _rate_limit(_limiter_autolabel, "sam", "Слишком много SAM-запросов. Подожди минуту.")
    pts = payload.points or []
    if len(pts) < 1: raise HTTPException(400, "Нужна хотя бы одна точка")
    if len(pts) > 8: raise HTTPException(400, "Максимум 8 точек")
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    name = get_sam_model_name(db)
    try:
        model = _get_sam_model(name)
    except ImportError:
        raise HTTPException(501, "ultralytics не установлен — SAM недоступен")
    except Exception as e:
        raise HTTPException(500, f"SAM не загружен: {e}")
    W, H = img.width or 640, img.height or 640
    points_px = [[float(p.x) * W, float(p.y) * H] for p in pts]
    labels = [1 if p.positive else 0 for p in pts]
    try:
        res = _run_sam_predict(model, img.path, points_px, labels)
    except Exception as e:
        raise HTTPException(500, f"SAM predict: {e}")
    if not res: return {"found": False}
    x1, y1, x2, y2 = res["bbox_px"]
    return {"found": True, "bbox": {"x": max(0.0, min(1.0, x1 / W)), "y": max(0.0, min(1.0, y1 / H)), "w": max(0.0, min(1.0, (x2 - x1) / W)), "h": max(0.0, min(1.0, (y2 - y1) / H))}, "score": res["score"], "mask": res["mask_b64"], "model": name}


# [STAGE1-A:behavior-audit]
@router.post("/api/images/{image_id}/behavior_audit")
def behavior_audit(image_id: int, payload: PredictBehaviorIn = Body(default_factory=PredictBehaviorIn),
                   db: Session = Depends(get_db)):
    """Сравнивает эвристику с ручной разметкой; возвращает согласие."""
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
        r = predict_behavior_from_keypoints(kps, motion=None, bbox=bbox)
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
def run_calibration(project_id: int, db: Session = Depends(get_db)):
    from services.behavior_service import calibrate_behavior_thresholds
    return calibrate_behavior_thresholds(db, project_id)

@router.delete("/api/projects/{project_id}/behavior/calibrate")
def reset_calibration(project_id: int, db: Session = Depends(get_db)):
    from models import Setting
    key = f"behavior_thresholds_{project_id}"
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        db.delete(row)
        db.commit()
    return {"status": "reset"}

@router.get("/api/projects/{project_id}/behavior/thresholds")
def get_behavior_thresholds(project_id: int, db: Session = Depends(get_db)):
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
