"""[V13.2.0:pipeline-service] Pipeline полной разметки проекта."""
import os
import threading
import time
import logging
from database import SessionLocal
from models import Project, ImageModel, Annotation, Keypoint, Video
from logger import log_status, utcnow
from services.ml_service import (
    get_active_model_path, get_active_pose_model_path,
    _get_yolo_model, _autolabel_batch_predict,
    _is_duplicate_box, _load_annotations,
    _apply_pose_detection_to_anns, _resolve_target_class_ids,
)
from services.behavior_service import predict_behavior_from_keypoints
from config import CONF_THRESHOLD

log = logging.getLogger("db")

PIPELINE_STATE = {
    "status": "idle",
    "stage": None,
    "stage_index": 0,
    "stage_total": 4,
    "stage_enabled": {},
    "stage_results": {},
    "message": "",
    "progress": 0.0,
    "stage_progress": 0.0,
    "stage_done": 0,
    "stage_total_items": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "log": [],
}
PIPELINE_LOCK = threading.Lock()
PIPELINE_STOP = threading.Event()
PIPELINE_THREAD = None
PIPELINE_EVENT = threading.Event()


def _snapshot():
    with PIPELINE_LOCK:
        return dict(PIPELINE_STATE)


def _set(**kw):
    with PIPELINE_LOCK:
        PIPELINE_STATE.update(kw)
    PIPELINE_EVENT.set()


def _log(msg):
    with PIPELINE_LOCK:
        PIPELINE_STATE["log"].append(msg)
        if len(PIPELINE_STATE["log"]) > 60:
            PIPELINE_STATE["log"] = PIPELINE_STATE["log"][-60:]
    log.info("[pipeline] %s", msg)
    PIPELINE_EVENT.set()


def _set_stage(stage, index, msg=""):
    _set(stage=stage, stage_index=index, message=msg,
         stage_progress=0.0, stage_done=0, stage_total_items=0)
    _log("Stage %d/4: %s" % (index, stage))


def _progress(stage_done, stage_total, msg=""):
    with PIPELINE_LOCK:
        idx = PIPELINE_STATE["stage_index"] or 1
        sp = (stage_done / stage_total * 100.0) if stage_total else 0.0
        overall = ((idx - 1) * 100.0 + sp) / PIPELINE_STATE["stage_total"]
        PIPELINE_STATE["stage_done"] = stage_done
        PIPELINE_STATE["stage_total_items"] = stage_total
        PIPELINE_STATE["stage_progress"] = sp
        PIPELINE_STATE["progress"] = overall
        if msg: PIPELINE_STATE["message"] = msg
    PIPELINE_EVENT.set()


def _mark_stage_result(stage, result):
    with PIPELINE_LOCK:
        PIPELINE_STATE["stage_results"] = dict(PIPELINE_STATE.get("stage_results") or {}, **{stage: result})
    PIPELINE_EVENT.set()


# [PATCH:STAGE4_PIPELINE_DIRECT_IMPORT]
from services.track_service import (
    _track_worker, TRACK_STOP, TRACK_STATE, TRACK_LOCK,
)
from services.motion_service import _check_motion
# [/PATCH:STAGE4_PIPELINE_DIRECT_IMPORT]


def _stage_autolabel(db, project_id, mode):
    # [PATCH:STAGE4-N14-autolabel]
    _set_stage("autolabel", 1, "Поиск активной YOLO-модели…")
    model_path = get_active_model_path(db)
    if not model_path:
        _log("Нет активной YOLO-модели — стадия пропущена")
        _mark_stage_result("autolabel", "skipped"); return "skipped"
    project = db.query(Project).filter(Project.id == project_id).first()
    target_label = (project.object_class if project else None) or "pig"
    try:
        model = _get_yolo_model(model_path)
    except Exception as e:
        _log("Модель не загрузилась: %s" % e)
        _mark_stage_result("autolabel", "skipped"); return "skipped"
    target_ids = _resolve_target_class_ids(model, target_label)
    if not target_ids:
        _log("Класс «%s» не поддерживается моделью" % target_label)
        _mark_stage_result("autolabel", "skipped"); return "skipped"

    if mode == "replace":
        _log("Replace mode: удаляю всю старую разметку проекта")
        img_ids = [row[0] for row in db.query(ImageModel.id).filter(
            ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)).all()]
        if img_ids:
            ann_ids = [row[0] for row in db.query(Annotation.id).filter(
                Annotation.image_id.in_(img_ids)).all()]
            if ann_ids:
                db.query(Keypoint).filter(Keypoint.annotation_id.in_(ann_ids)).delete(synchronize_session=False)
            db.query(Annotation).filter(Annotation.image_id.in_(img_ids)).delete(synchronize_session=False)
            db.commit()

    imgs = db.query(ImageModel).filter(
        ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)).all()
    total = len(imgs)
    if total == 0:
        _log("Нет изображений")
        _mark_stage_result("autolabel", "skipped"); return "skipped"
    _set(stage_total_items=total)

    batch_size = 4
    try:
        import torch
        if torch.cuda.is_available(): batch_size = 16
    except Exception: pass

    done, added, skipped = 0, 0, 0
    for chunk_start in range(0, total, batch_size):
        if PIPELINE_STOP.is_set(): return "stopped"
        chunk = imgs[chunk_start:chunk_start + batch_size]
        paths, wl, hl, ok_imgs = [], [], [], []
        for img in chunk:
            if img.path and os.path.exists(img.path):
                paths.append(img.path); wl.append(img.width or 640)
                hl.append(img.height or 640); ok_imgs.append(img)
        if not paths:
            done += len(chunk); _progress(done, total); continue
        try:
            batch_results = _autolabel_batch_predict(paths, model, wl, hl, target_ids, target_label)
        except Exception as e:
            _log("Batch predict error: %s" % e)
            db.rollback(); done += len(chunk); _progress(done, total); continue

        for img, raw_new in zip(ok_imgs, batch_results):
            if mode == "add":
                existing = _load_annotations(db, img.id)
                existing_xywh = [{"x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"]} for e in existing]
                unique = []
                for d in raw_new:
                    if any(_is_duplicate_box(d, e) for e in existing_xywh):
                        skipped += 1
                    else:
                        unique.append(d)
                for a in unique:
                    db.add(Annotation(image_id=img.id, x=a["x"], y=a["y"], w=a["w"], h=a["h"],
                                      label=target_label, confidence=a.get("confidence"),
                                      is_frozen=False, behavior=None, animal_id=None))
                added += len(unique)
            else:
                for a in raw_new:
                    db.add(Annotation(image_id=img.id, x=a["x"], y=a["y"], w=a["w"], h=a["h"],
                                      label=target_label, confidence=a.get("confidence"),
                                      is_frozen=False, behavior=None, animal_id=None))
                added += len(raw_new)
            done += 1
        try: db.commit()
        except Exception as e:
            db.rollback(); _log("DB commit error: %s" % e)
        _progress(done, total, "Рамки: %d/%d (+%d, пропущено %d)" % (done, total, added, skipped))
    _log("Autolabel завершён: +%d, пропущено %d" % (added, skipped))
    _progress(total, total, "Рамки: +%d, пропущено %d" % (added, skipped))
    _mark_stage_result("autolabel", "done"); return "done"


def _stage_pose(db, project_id, mode):
    _set_stage("pose", 2, "Поиск pose-модели…")
    model_path = get_active_pose_model_path(db)
    if not model_path:
        _log("Pose-модель не найдена — стадия пропущена")
        _mark_stage_result("pose", "skipped"); return "skipped"
    try: model = _get_yolo_model(model_path)
    except Exception as e:
        _log("Pose-модель не загрузилась: %s" % e)
        _mark_stage_result("pose", "skipped"); return "skipped"

    imgs = db.query(ImageModel).filter(
        ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)).all()
    total = len(imgs)
    if total == 0:
        _mark_stage_result("pose", "skipped"); return "skipped"
    _set(stage_total_items=total)

    done, boxes_ok, kps_ok, skipped_ex = 0, 0, 0, 0
    only_empty = (mode == "add")  # [PATCH:STAGE4-N11-pose-mode]
    for img in imgs:
        if PIPELINE_STOP.is_set(): return "stopped"
        anns = db.query(Annotation).filter(Annotation.image_id == img.id).all()
        if not anns:
            done += 1; _progress(done, total); continue
        try:
            results = model(img.path, conf=0.25, verbose=False)
            summary = _apply_pose_detection_to_anns(db, img, results,
                                                     only_empty=only_empty,
                                                     iou_threshold=0.30)
            boxes_ok += summary.get("saved_annotations", 0)
            kps_ok += summary.get("saved_keypoints", 0)
            skipped_ex += summary.get("skipped_existing", 0)
        except Exception as e:
            _log("Pose error img=%s: %s" % (img.id, e))
            try: db.rollback()
            except Exception: pass
        done += 1
        if done % 10 == 0:
            _progress(done, total, "Скелеты: %d/%d (рамок %d)" % (done, total, boxes_ok))
    _log("Pose завершён: рамок %d, точек %d, пропущено %d" % (boxes_ok, kps_ok, skipped_ex))
    _progress(total, total, "Скелеты: рамок %d, точек %d" % (boxes_ok, kps_ok))
    _mark_stage_result("pose", "done"); return "done"


def _stage_track(db, project_id, mode):
    _set_stage("track", 3, "Поиск видео…")
    videos = db.query(Video).filter(Video.project_id == project_id, Video.is_deleted.is_(False)).all()
    if not videos:
        _log("Видео нет — трекинг пропущен")
        _mark_stage_result("track", "skipped"); return "skipped"
    model_path = get_active_model_path(db)
    if not model_path:
        _log("Нет активной YOLO-модели — трекинг невозможен")
        _mark_stage_result("track", "skipped"); return "skipped"

    # [PATCH:STAGE4_PIPELINE_TRACK] импортируется напрямую из track_service
    _TRACK_STOP = TRACK_STOP
    _TRACK_STATE = TRACK_STATE
    _TRACK_LOCK = TRACK_LOCK
    # [/PATCH:STAGE4_PIPELINE_TRACK]

    total = len(videos)
    _set(stage_total_items=total)
    done = 0
    for video in videos:
        if PIPELINE_STOP.is_set(): return "stopped"
        frames = db.query(ImageModel.id).filter(
            ImageModel.video_id == video.id, ImageModel.is_deleted.is_(False)).count()
        if frames == 0:
            done += 1; _progress(done, total); continue
        _log("Трекинг видео #%d «%s» (%d кадров)" % (video.id, video.filename, frames))
        _TRACK_STOP.clear()
        t = threading.Thread(target=_track_worker,
                             args=(video.id, project_id, model_path), daemon=True)
        t.start()
        while t.is_alive():
            if PIPELINE_STOP.is_set():
                _TRACK_STOP.set()
                t.join(timeout=15)
                return "stopped"
            time.sleep(0.6)
            try:
                with _TRACK_LOCK:
                    df = _TRACK_STATE.get("done", 0)
                    tf = _TRACK_STATE.get("total", frames) or frames
                inner = (df / tf * 100.0) if tf else 0.0
                overall = ((done + inner / 100.0) / total) * 100.0
                with PIPELINE_LOCK:
                    PIPELINE_STATE["stage_progress"] = inner
                    PIPELINE_STATE["progress"] = (2 * 100.0 + overall) / 4.0
                    PIPELINE_STATE["message"] = "Трекинг видео #%d: %d/%d кадров" % (video.id, df, tf)
                PIPELINE_EVENT.set()
            except Exception: pass
        done += 1
        _progress(done, total, "Трекинг: видео %d/%d" % (done, total))
    _log("Трекинг завершён")
    _mark_stage_result("track", "done"); return "done"


def _stage_behavior(db, project_id, mode):
    _set_stage("behavior", 4, "Определение поведения…")
    imgs = db.query(ImageModel).filter(
        ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)).all()
    total = len(imgs)
    if total == 0:
        _mark_stage_result("behavior", "skipped"); return "skipped"
    _set(stage_total_items=total)

    # [PATCH:STAGE4_PIPELINE_BEHAVIOR] _check_motion импортируется из motion_service
    # [/PATCH:STAGE4_PIPELINE_BEHAVIOR]

    done, applied, skipped = 0, 0, 0
    only_empty = (mode == "add")
    for img in imgs:
        if PIPELINE_STOP.is_set(): return "stopped"
        anns = db.query(Annotation).filter(Annotation.image_id == img.id).all()
        if not anns:
            done += 1; _progress(done, total); continue
        for a in anns:
            if only_empty and a.behavior:
                skipped += 1; continue
            kps = [{"name": k.name, "x": k.x, "y": k.y, "visibility": k.visibility}
                   for k in db.query(Keypoint).filter(Keypoint.annotation_id == a.id).all()]
            if not kps:
                skipped += 1; continue
            motion = None
            if a.animal_id is not None and _check_motion is not None:
                try: motion = _check_motion(db, img.id, a.animal_id)
                except Exception: motion = None
            bbox = {"x": a.x, "y": a.y, "w": a.w, "h": a.h}
            try:
                r = predict_behavior_from_keypoints(kps, motion=motion, bbox=bbox, project_id=project_id)
            except Exception:
                skipped += 1; continue
            b = r.get("behavior")
            if b:
                a.behavior = b
                # [FIX:v1341-backend] правильный source
                _src = r.get("source") or "heuristic"
                try:
                    a.behavior_source = _src
                except Exception:
                    pass
                applied += 1
            else:
                skipped += 1
        try: db.commit()
        except Exception as e:
            db.rollback(); _log("Behavior commit error: %s" % e)
        done += 1
        if done % 10 == 0:
            _progress(done, total, "Поведение: %d/%d (установлено %d)" % (done, total, applied))
    _log("Behavior завершён: установлено %d, пропущено %d" % (applied, skipped))
    _progress(total, total, "Поведение: установлено %d" % applied)
    _mark_stage_result("behavior", "done"); return "done"


def _pipeline_worker(project_id, mode, enabled_stages):
    global PIPELINE_THREAD
    db = SessionLocal()
    try:
        _set(status="running", started_at=utcnow().isoformat(), finished_at=None,
             error=None, progress=0.0, stage_index=0,
             stage_enabled=dict(enabled_stages), stage_results={},
             log=["Pipeline запущен"])
        _log("Mode: %s. Этапы: %s" % (mode, [k for k, v in enabled_stages.items() if v]))

        stage_fns = [
            ("autolabel", _stage_autolabel),
            ("pose", _stage_pose),
            ("track", _stage_track),
            ("behavior", _stage_behavior),
        ]
        for idx, (name, fn) in enumerate(stage_fns, start=1):
            if PIPELINE_STOP.is_set():
                _set(status="stopped", message="Остановлено пользователем",
                     finished_at=utcnow().isoformat())
                return
            if not enabled_stages.get(name):
                _log("Stage %d/4: %s — отключён" % (idx, name))
                _mark_stage_result(name, "disabled")
                continue
            result = fn(db, project_id, mode)
            if result == "stopped":
                _set(status="stopped", message="Остановлено на этапе %s" % name,
                     finished_at=utcnow().isoformat())
                return
            _log("Stage %d/4: %s → %s" % (idx, name, result))

        _set(status="done", progress=100.0, finished_at=utcnow().isoformat(),
             message="Готово")
        log_status("success", "system", "Pipeline завершён (mode=%s)" % mode)
    except Exception as e:
        log.exception("pipeline failed")
        try: db.rollback()
        except Exception: pass
        _set(status="error", error=str(e), message="Ошибка: %s" % e,
             finished_at=utcnow().isoformat())
        log_status("error", "system", "Pipeline упал: %s" % e)
    finally:
        try: db.close()
        except Exception: pass
        with PIPELINE_LOCK:
            PIPELINE_THREAD = None
        PIPELINE_EVENT.set()


def start_pipeline(project_id, mode="add", enabled_stages=None):
    global PIPELINE_THREAD
    if mode not in ("add", "replace"): mode = "add"
    with PIPELINE_LOCK:
        if PIPELINE_STATE["status"] in ("running", "stopping"):
            raise RuntimeError("Pipeline уже запущен")
    # [PATCH:STAGE4_PIPELINE_START] проверка через track_service
    with TRACK_LOCK:
        if TRACK_STATE.get("status") == "running":
            raise RuntimeError("Идёт одиночный трекинг. Дождитесь окончания.")
    # [/PATCH:STAGE4_PIPELINE_START]

    PIPELINE_STOP.clear()
    PIPELINE_EVENT.clear()
    default_stages = {"autolabel": True, "pose": True, "track": True, "behavior": True}
    if enabled_stages:
        default_stages.update({k: bool(v) for k, v in enabled_stages.items() if k in default_stages})
    with PIPELINE_LOCK:
        PIPELINE_STATE.update({
            "status": "running", "stage": None, "stage_index": 0, "progress": 0.0,
            "message": "Запуск…", "started_at": utcnow().isoformat(),
            "finished_at": None, "error": None, "log": [],
            "stage_enabled": dict(default_stages), "stage_results": {},
        })
    t = threading.Thread(target=_pipeline_worker,
                         args=(project_id, mode, default_stages),
                         daemon=True, name="pipeline")
    with PIPELINE_LOCK:
        PIPELINE_THREAD = t
    t.start()


def stop_pipeline():
    PIPELINE_STOP.set()
    TRACK_STOP.set()  # [PATCH:STAGE4_PIPELINE_STOP] через track_service
    with PIPELINE_LOCK:
        if PIPELINE_STATE["status"] == "running":
            PIPELINE_STATE["status"] = "stopping"
            PIPELINE_STATE["message"] = "Останавливаю…"
    PIPELINE_EVENT.set()

# [STAGE6:TRACK-CIRCULAR-TODO] Полный вынос трекинга в track_service
# отложен — текущий _import_track_module() минимально безопасен.
# TODO Stage 6+: создать services/track_service.py и импортировать его.
