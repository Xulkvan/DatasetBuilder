from fastapi import APIRouter, HTTPException, Form, Depends, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import timedelta
from typing import Optional

from database import get_db
from models import Project, ImageModel, Annotation, Tag, ImageTag
from schemas import ProjectSettingsIn
from logger import utcnow, log_status
from services.image_service import _invalidate_stats_cache
from services.project_service import _purge_projects
from services.settings_service import get_trash_ttl_days


import re
from fastapi import HTTPException
from config import MAX_OBJECT_CLASS_LEN

def _validate_object_class(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise HTTPException(400, "Имя класса не может быть пустым")
    if len(n) > MAX_OBJECT_CLASS_LEN:
        raise HTTPException(400, f"Слишком длинное имя класса (макс. {MAX_OBJECT_CLASS_LEN})")
    if not re.match(r"^[\w\s\-\.\'\(\)/]+$", n, flags=re.UNICODE):
        raise HTTPException(400, "Недопустимые символы в имени класса")
    return n

def _validate_object_class_source(src: str) -> str:
    s = (src or "").strip().lower()
    if s not in ("list", "custom"):
        return "list"
    return s

router = APIRouter()

@router.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    rows = (db.query(Project).filter(Project.is_deleted.is_(False)).order_by(Project.id).all())
    counts = dict(db.query(ImageModel.project_id, func.count(ImageModel.id)).filter(ImageModel.is_deleted.is_(False)).group_by(ImageModel.project_id).all())
    ann_counts = dict(db.query(ImageModel.project_id, func.count(Annotation.id)).join(Annotation, Annotation.image_id == ImageModel.id).filter(ImageModel.is_deleted.is_(False)).group_by(ImageModel.project_id).all())
    return [{
        "id": p.id, "name": p.name, "images_count": int(counts.get(p.id, 0)),
        "annotations_count": int(ann_counts.get(p.id, 0)),
        "object_class": p.object_class or "pig", "object_class_source": p.object_class_source or "list",
        "trash_ttl_days_override": p.trash_ttl_days_override, "thumbnail_size": p.thumbnail_size, "default_zoom": p.default_zoom,
    } for p in rows]

@router.post("/api/projects")
def create_project(name: str = Form(...), object_class: str = Form("pig"), object_class_source: str = Form("list"), db: Session = Depends(get_db)):
    name = name.strip()
    if not name: raise HTTPException(400, {"key": "error.emptyProjectName", "fallback": "Пустое имя проекта"})
    if len(name) > 255: raise HTTPException(400, "Слишком длинное имя")
    cls = _validate_object_class(object_class)
    src = _validate_object_class_source(object_class_source)
    p = Project(name=name, created_at=utcnow(), is_deleted=False, object_class=cls, object_class_source=src)
    db.add(p); db.commit(); db.refresh(p)
    log_status("success", "project", f"Создан проект «{name}» (id={p.id}, класс={cls})")
    return {"id": p.id, "name": p.name, "images_count": 0, "annotations_count": 0, "object_class": p.object_class, "object_class_source": p.object_class_source}

@router.delete("/api/projects/{project_id}")
def soft_delete_project(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj: raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    if proj.is_deleted: return {"status": "ok", "deleted_id": project_id, "soft": True, "already_deleted": True}
    proj.is_deleted = True; proj.deleted_at = utcnow(); db.commit()
    log_status("warning", "project", f"Проект «{proj.name}» перемещён в корзину")
    return {"status": "ok", "deleted_id": project_id, "soft": True, "name": proj.name}

@router.post("/api/projects/{project_id}/restore")
def restore_project(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj: raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    if not proj.is_deleted: return {"status": "ok", "restored_id": project_id, "name": proj.name, "already_active": True}
    proj.is_deleted = False; proj.deleted_at = None; db.commit()
    log_status("info", "project", f"Проект «{proj.name}» восстановлен из корзины")
    return {"status": "ok", "restored_id": project_id, "name": proj.name}

@router.delete("/api/projects/{project_id}/permanent")
def permanent_delete_project(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj: raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    name = proj.name
    _purge_projects(db, [project_id])
    log_status("warning", "project", f"Проект «{name}» удалён навсегда")
    return {"status": "ok", "deleted_id": project_id, "permanent": True}

@router.get("/api/projects/{project_id}/info")
def project_info(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj: raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    images_count = (db.query(func.count(ImageModel.id)).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)).scalar() or 0)
    ann_count = (db.query(func.count(Annotation.id)).join(ImageModel, Annotation.image_id == ImageModel.id).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)).scalar() or 0)
    return {"id": proj.id, "name": proj.name, "object_class": proj.object_class or "pig", "object_class_source": proj.object_class_source or "list", "images_count": int(images_count), "annotations_count": int(ann_count), "is_deleted": bool(proj.is_deleted), "trash_ttl_days_override": proj.trash_ttl_days_override, "thumbnail_size": proj.thumbnail_size, "default_zoom": proj.default_zoom, "global_trash_ttl": get_trash_ttl_days(db), "auto_blur_enabled": bool(getattr(proj, "auto_blur_enabled", False)), "auto_blur_classes": getattr(proj, "auto_blur_classes", None)}

@router.patch("/api/projects/{project_id}/settings")
def update_project_settings(project_id: int, payload: ProjectSettingsIn, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj: raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    changed = []
    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name: raise HTTPException(400, "Имя проекта не может быть пустым")
        if len(new_name) > 255: raise HTTPException(400, "Слишком длинное имя проекта")
        if proj.name != new_name: proj.name = new_name; changed.append("name")
    if payload.object_class is not None:
        new_class = _validate_object_class(payload.object_class)
        new_src = _validate_object_class_source(payload.object_class_source if payload.object_class_source is not None else (proj.object_class_source or "list"))
        if (proj.object_class or "pig") != new_class or (proj.object_class_source or "list") != new_src:
            ann_count = (db.query(func.count(Annotation.id)).join(ImageModel, Annotation.image_id == ImageModel.id).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)).scalar() or 0)
            if ann_count > 0: raise HTTPException(409, f"В проекте уже размечено {ann_count} рамок.")
            proj.object_class = new_class; proj.object_class_source = new_src; changed.append(f"класс={new_class}")
    if payload.clear_ttl_override:
        if proj.trash_ttl_days_override is not None: proj.trash_ttl_days_override = None; changed.append("ttl=global")
    elif payload.trash_ttl_days_override is not None:
        v = max(0, min(3650, int(payload.trash_ttl_days_override)))
        if proj.trash_ttl_days_override != v: proj.trash_ttl_days_override = v; changed.append(f"ttl={v}")
    if payload.clear_thumbnail_size:
        if proj.thumbnail_size is not None: proj.thumbnail_size = None; changed.append("thumb=default")
    elif payload.thumbnail_size is not None:
        v = int(payload.thumbnail_size)
        if v not in (32, 48, 64, 96): raise HTTPException(400, "thumbnail_size должен быть 32, 48, 64 или 96")
        if proj.thumbnail_size != v: proj.thumbnail_size = v; changed.append(f"thumb={v}")
    if payload.clear_default_zoom:
        if proj.default_zoom is not None: proj.default_zoom = None; changed.append("zoom=default")
    elif payload.default_zoom is not None:
        v = float(payload.default_zoom)
        if v not in (None, 1.0, 1.5, 2.0, 3.0, 4.0): raise HTTPException(400, "default_zoom некорректен")
        if proj.default_zoom != v: proj.default_zoom = v; changed.append(f"zoom={v}")
    # [FIX:v1341-backend] auto-blur settings
    if getattr(payload, "auto_blur_enabled", None) is not None:
        v = bool(payload.auto_blur_enabled)
        if bool(getattr(proj, "auto_blur_enabled", False)) != v:
            proj.auto_blur_enabled = v
            changed.append(f"auto_blur={'on' if v else 'off'}")
    if getattr(payload, "auto_blur_classes", None) is not None:
        import json as _json
        try:
            v = _json.dumps(list(payload.auto_blur_classes))
        except Exception:
            raise HTTPException(400, "auto_blur_classes должен быть списком")
        if (getattr(proj, "auto_blur_classes", None) or None) != v:
            proj.auto_blur_classes = v
            changed.append("auto_blur_classes")
    if not changed: return {"status": "noop"}
    db.commit()
    log_status("info", "project", f"Проект «{proj.name}»: изменения — {', '.join(changed)}")
    return {"id": proj.id, "object_class": proj.object_class, "object_class_source": proj.object_class_source, "trash_ttl_days_override": proj.trash_ttl_days_override, "thumbnail_size": proj.thumbnail_size, "default_zoom": proj.default_zoom}

@router.post("/api/projects/{project_id}/clear_annotations")
def clear_project_annotations(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj: raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    img_ids_q = db.query(ImageModel.id).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False))
    img_ids = [iid for (iid,) in img_ids_q.all()]
    if not img_ids: return {"status": "ok", "cleared": 0}
    total = (db.query(func.count(Annotation.id)).filter(Annotation.image_id.in_(img_ids)).scalar() or 0)
    db.query(Annotation).filter(Annotation.image_id.in_(img_ids)).delete(synchronize_session=False)
    db.commit()
    _invalidate_stats_cache(project_id)
    log_status("warning", "project", f"Проект «{proj.name}»: очищено рамок {total}")
    return {"status": "ok", "cleared": int(total)}

@router.get("/api/projects/trash")
def list_projects_trash(db: Session = Depends(get_db)):
    rows = db.query(Project).filter(Project.is_deleted.is_(True)).order_by(Project.deleted_at.desc(), Project.id.desc()).all()
    ttl = get_trash_ttl_days(db)
    now = utcnow()
    out = []
    for r in rows:
        cnt = db.query(func.count(ImageModel.id)).filter(ImageModel.project_id == r.id).scalar() or 0
        days_left = None
        eff_ttl = r.trash_ttl_days_override if r.trash_ttl_days_override is not None else ttl
        if r.deleted_at and eff_ttl > 0: days_left = max(0, (r.deleted_at + timedelta(days=eff_ttl) - now).days)
        out.append({"id": r.id, "name": r.name, "images_count": int(cnt), "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None, "days_left": days_left})
    return out

@router.post("/api/projects/trash/empty")
def empty_projects_trash(db: Session = Depends(get_db)):
    ids = [r.id for r in db.query(Project.id).filter(Project.is_deleted.is_(True)).all()]
    if not ids: return {"status": "ok", "deleted": 0}
    _purge_projects(db, ids)
    return {"status": "ok", "deleted": len(ids)}

from services.image_service import get_project_stats_cached

@router.get("/api/projects/{project_id}/stats")
def project_stats(project_id: int, db: Session = Depends(get_db)):
    # [V13.1.0:stats]
    res = get_project_stats_cached(project_id, db)

    # Добавляем расширенную статистику
    from models import ImageModel, Annotation, Keypoint, ImageTag
    from sqlalchemy import func
    from collections import Counter

    # 1. Распределение поведения
    beh_rows = db.query(Annotation.behavior, func.count(Annotation.id)).join(ImageModel).filter(ImageModel.project_id == project_id, ImageModel.is_deleted == False, Annotation.behavior.isnot(None)).group_by(Annotation.behavior).all()
    res["behavior_dist"] = {b: c for b, c in beh_rows}

    # 2. Источник поведения
    src_rows = db.query(Annotation.behavior_source, func.count(Annotation.id)).join(ImageModel).filter(ImageModel.project_id == project_id, ImageModel.is_deleted == False, Annotation.behavior.isnot(None)).group_by(Annotation.behavior_source).all()
    res["behavior_source_dist"] = {s or 'unknown': c for s, c in src_rows}

    # 3. Треки (одиночки vs длинные)
    track_rows = db.query(Annotation.animal_id, func.count(Annotation.id)).join(ImageModel).filter(ImageModel.project_id == project_id, ImageModel.is_deleted == False, Annotation.animal_id.isnot(None)).group_by(Annotation.animal_id).all()
    single = sum(1 for _, c in track_rows if c == 1)
    long = sum(1 for _, c in track_rows if c >= 10)
    res["track_stats"] = {"total": len(track_rows), "single": single, "long": long}

    return res


# [STAGE1-A:kappa]
@router.get("/api/projects/{project_id}/behavior_agreement")
def behavior_agreement(project_id: int, db: Session = Depends(get_db)):
    """Cohen's kappa между ручным поведением и эвристикой."""
    from services.behavior_service import predict_behavior_from_keypoints
    from models import Keypoint
    anns = (db.query(Annotation)
              .join(ImageModel, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False),
                      Annotation.behavior.isnot(None))
              .all())
    pairs = []
    for a in anns:
        kps = [{"name": k.name, "x": k.x, "y": k.y, "visibility": k.visibility}
               for k in db.query(Keypoint).filter(Keypoint.annotation_id == a.id).all()]
        if not kps:
            continue
        bbox = {"x": a.x, "y": a.y, "w": a.w, "h": a.h}
        r = predict_behavior_from_keypoints(kps, bbox=bbox)
        h = r.get("behavior")
        if h:
            pairs.append((a.behavior, h))
    n = len(pairs)
    if n == 0:
        return {"n": 0, "kappa": None, "note": "no_pairs"}
    labels = sorted(set([p[0] for p in pairs] + [p[1] for p in pairs]))
    idx = {l: i for i, l in enumerate(labels)}
    mat = [[0] * len(labels) for _ in labels]
    for human, heur in pairs:
        mat[idx[human]][idx[heur]] += 1
    po = sum(mat[i][i] for i in range(len(labels))) / n
    row_sum = [sum(row) for row in mat]
    col_sum = [sum(mat[i][j] for i in range(len(labels))) for j in range(len(labels))]
    pe = sum(row_sum[i] * col_sum[i] for i in range(len(labels))) / (n * n)
    kappa = (po - pe) / (1 - pe) if (1 - pe) != 0 else None
    return {"n": n, "po": round(po, 4), "pe": round(pe, 4),
            "kappa": round(kappa, 4) if kappa is not None else None,
            "labels": labels, "matrix": mat}


# [STAGE1-B:track-quality]
@router.get("/api/projects/{project_id}/tracks/quality")
def tracks_quality(project_id: int, db: Session = Depends(get_db)):
    from collections import defaultdict
    rows = (db.query(Annotation.animal_id, ImageModel.id, ImageModel.video_id, ImageModel.frame_index)
              .join(ImageModel, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False),
                      Annotation.animal_id.isnot(None))
              .all())
    by_aid = defaultdict(list)
    for aid, iid, vid, fidx in rows:
        by_aid[int(aid)].append((vid, fidx or 0))
    single_frame = []
    big_gaps = []
    for aid, frames in by_aid.items():
        if len(frames) == 1:
            single_frame.append(aid)
            continue
        frames_sorted = sorted(frames, key=lambda x: (x[0] or 0, x[1]))
        for i in range(1, len(frames_sorted)):
            v1, f1 = frames_sorted[i-1]
            v2, f2 = frames_sorted[i]
            if v1 != v2:
                continue
            gap = f2 - f1
            if gap > 3:
                big_gaps.append({"animal_id": aid, "from_frame": f1, "to_frame": f2, "gap": gap})
    total_tracks = len(by_aid)
    return {
        "total_tracks": total_tracks,
        "single_frame_tracks": single_frame,
        "single_frame_pct": (len(single_frame) / total_tracks * 100) if total_tracks else 0.0,
        "big_gaps": sorted(big_gaps, key=lambda x: -x["gap"])[:20],
    }

# [STAGE1:projects-version] Снимок версии датасета
@router.post("/api/projects/{project_id}/version")
def create_dataset_version(project_id: int, db: Session = Depends(get_db)):
    from models import DatasetVersion
    from services.versioning_service import calculate_dataset_hash
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    h = calculate_dataset_hash(db, project_id)
    img_count = int(db.query(func.count(ImageModel.id)).filter(
        ImageModel.project_id == project_id,
        ImageModel.is_deleted.is_(False)).scalar() or 0)
    ann_count = int(db.query(func.count(Annotation.id)).join(
        ImageModel, Annotation.image_id == ImageModel.id).filter(
        ImageModel.project_id == project_id,
        ImageModel.is_deleted.is_(False)).scalar() or 0)
    row = DatasetVersion(project_id=project_id, hash=h,
                         created_at=utcnow(),
                         image_count=img_count,
                         annotation_count=ann_count)
    db.add(row); db.commit(); db.refresh(row)
    log_status("info", "project",
               f"Snapshot проекта #{project_id}: hash={h[:12]}…")
    return {"id": row.id, "hash": h,
            "image_count": img_count, "annotation_count": ann_count,
            "created_at": row.created_at.isoformat() if row.created_at else None}


@router.get("/api/projects/{project_id}/versions")
def list_dataset_versions(project_id: int, db: Session = Depends(get_db)):
    from models import DatasetVersion
    rows = (db.query(DatasetVersion)
              .filter(DatasetVersion.project_id == project_id)
              .order_by(DatasetVersion.id.desc())
              .limit(50).all())
    return [{"id": r.id, "hash": r.hash,
             "image_count": r.image_count,
             "annotation_count": r.annotation_count,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]

# ============================================================================
# [STAGE2:business-exports] Parquet, SQL, CVAT
# ============================================================================
@router.get("/api/projects/{project_id}/export/parquet")
def export_parquet(project_id: int, db: Session = Depends(get_db)):
    import io as _io
    import zipfile as _zip
    try:
        import pandas as _pd
    except ImportError:
        raise HTTPException(501, "pandas не установлен — Parquet недоступен")
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    rows = (db.query(Annotation, ImageModel)
              .join(ImageModel, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False)).all())
    data = []
    for a, im in rows:
        data.append({
            "image_id": im.id,
            "filename": im.filename,
            "video_id": im.video_id,
            "frame_index": im.frame_index,
            "timestamp_sec": im.timestamp_sec,
            "x": a.x, "y": a.y, "w": a.w, "h": a.h,
            "label": a.label,
            "confidence": a.confidence,
            "frozen": bool(a.is_frozen),
            "behavior": a.behavior,
            "animal_id": a.animal_id,
        })
    df = _pd.DataFrame(data)
    csv_buf = _io.BytesIO()
    df.to_csv(csv_buf, index=False, encoding="utf-8")
    parquet_buf = _io.BytesIO()
    try:
        df.to_parquet(parquet_buf, index=False)
    except Exception:
        parquet_buf = None
    zip_buf = _io.BytesIO()
    with _zip.ZipFile(zip_buf, "w", _zip.ZIP_DEFLATED) as z:
        z.writestr("annotations.csv", csv_buf.getvalue())
        if parquet_buf is not None:
            z.writestr("annotations.parquet", parquet_buf.getvalue())
    from fastapi.responses import Response as _Resp
    return _Resp(content=zip_buf.getvalue(),
                 media_type="application/zip",
                 headers={"Content-Disposition":
                          f"attachment; filename=parquet_project_{project_id}.zip"})


@router.get("/api/projects/{project_id}/export/sql")
def export_sql_dump(project_id: int, db: Session = Depends(get_db)):
    import io as _io
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    imgs = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False)).all())
    img_ids = [im.id for im in imgs]
    anns = []
    if img_ids:
        anns = (db.query(Annotation)
                  .filter(Annotation.image_id.in_(img_ids)).all())
    buf = _io.StringIO()
    buf.write("-- DatasetBuilder annotation dump\n")
    buf.write("-- project: %s (id=%s)\n\n" % (proj.name, proj.id))
    buf.write("CREATE TABLE IF NOT EXISTS annotations_dump (\n")
    buf.write("  image_id INTEGER, filename TEXT, video_id INTEGER,\n")
    buf.write("  frame_index INTEGER, x REAL, y REAL, w REAL, h REAL,\n")
    buf.write("  label TEXT, behavior TEXT, animal_id INTEGER\n);\n\n")
    def esc(v):
        if v is None: return "NULL"
        if isinstance(v, (int, float)): return str(v)
        return "'" + str(v).replace("'", "''") + "'"
    for a in anns:
        im = next((i for i in imgs if i.id == a.image_id), None)
        if im is None:
            continue
        buf.write("INSERT INTO annotations_dump VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);\n" % (
            esc(im.id), esc(im.filename), esc(im.video_id), esc(im.frame_index),
            esc(a.x), esc(a.y), esc(a.w), esc(a.h),
            esc(a.label), esc(a.behavior), esc(a.animal_id)))
    from fastapi.responses import Response as _Resp
    return _Resp(content=buf.getvalue().encode("utf-8"),
                 media_type="application/sql; charset=utf-8",
                 headers={"Content-Disposition":
                          f"attachment; filename=sql_project_{project_id}.sql"})


@router.get("/api/projects/{project_id}/export/cvat")
def export_cvat(project_id: int, db: Session = Depends(get_db)):
    from services.cvat_service import export_cvat_xml
    from fastapi.responses import Response as _Resp
    try:
        body = export_cvat_xml(db, project_id)
    except ValueError:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    return _Resp(content=body, media_type="application/xml; charset=utf-8",
                 headers={"Content-Disposition":
                          f"attachment; filename=cvat_project_{project_id}.xml"})


@router.get("/api/projects/{project_id}/dataset_card")
def get_dataset_card(project_id: int, db: Session = Depends(get_db)):
    from services.dataset_card_service import generate_dataset_card
    from fastapi.responses import Response as _Resp
    md = generate_dataset_card(db, project_id)
    return _Resp(content=md.encode("utf-8"),
                 media_type="text/markdown; charset=utf-8",
                 headers={"Content-Disposition":
                          f"attachment; filename=dataset_card_{project_id}.md"})


# ============================================================================
# [STAGE2:projects-extensions] diff версий + кастомная схема скелета.
# ============================================================================
from fastapi import Body as _Body  # noqa: E402


@router.get("/api/projects/{project_id}/versions/diff")
def versions_diff(project_id: int,
                  hash1: str = "",
                  hash2: str = "",
                  db: Session = Depends(get_db)):
    """GET /api/projects/{id}/versions/diff?hash1=...&hash2=..."""
    from services.versioning_service import calculate_dataset_diff
    if not hash1 or not hash2:
        raise HTTPException(400, "hash1 и hash2 обязательны")
    proj = (db.query(Project)
              .filter(Project.id == project_id).first())
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    diff = calculate_dataset_diff(db, project_id, hash1, hash2)
    if diff.get("error") == "version_not_found":
        raise HTTPException(404, diff)
    return diff


@router.get("/api/projects/{project_id}/keypoint_schema")
def get_project_keypoint_schema(project_id: int,
                                db: Session = Depends(get_db)):
    from models import ProjectKeypointSchema
    from config import KEYPOINT_SCHEMA
    row = (db.query(ProjectKeypointSchema)
             .filter(ProjectKeypointSchema.project_id == project_id).first())
    if row and row.schema_json:
        import json as _json
        try:
            custom = _json.loads(row.schema_json)
            return {"project_id": project_id, "source": "custom",
                    "schema": custom}
        except Exception:
            pass
    return {
        "project_id": project_id,
        "source": "default",
        "schema": [
            {"name": n, "label_ru": ru, "label_en": en, "parent": p}
            for (n, ru, en, p) in KEYPOINT_SCHEMA
        ],
    }


@router.put("/api/projects/{project_id}/keypoint_schema")
def put_project_keypoint_schema(project_id: int,
                                payload: dict = _Body(...),
                                db: Session = Depends(get_db)):
    from models import ProjectKeypointSchema
    proj = (db.query(Project)
              .filter(Project.id == project_id).first())
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    schema = payload.get("schema")
    if not isinstance(schema, list) or not schema:
        raise HTTPException(400, "schema должен быть непустым массивом")
    for pt in schema:
        if not isinstance(pt, dict) or not pt.get("name"):
            raise HTTPException(400, "Каждая точка должна иметь 'name'")
    import json as _json
    row = (db.query(ProjectKeypointSchema)
             .filter(ProjectKeypointSchema.project_id == project_id).first())
    if row is None:
        row = ProjectKeypointSchema(project_id=project_id,
                                    schema_json=_json.dumps(schema))
        db.add(row)
    else:
        row.schema_json = _json.dumps(schema)
    db.commit()
    return {"project_id": project_id, "source": "custom",
            "schema": schema, "count": len(schema)}


@router.delete("/api/projects/{project_id}/keypoint_schema")
def reset_project_keypoint_schema(project_id: int,
                                  db: Session = Depends(get_db)):
    from models import ProjectKeypointSchema
    db.query(ProjectKeypointSchema).filter(
        ProjectKeypointSchema.project_id == project_id
    ).delete(synchronize_session=False)
    db.commit()
    return {"project_id": project_id, "source": "default"}
# [/STAGE2:projects-extensions]


# ============================================================================
# [STAGE3:projects-extensions] Active Learning + RTSP streams + ML classifier.
# ============================================================================
@router.get("/api/projects/{project_id}/active_learning_queue")
def active_learning_queue(project_id: int, limit: int = 50,
                          db: Session = Depends(get_db)):
    """Неразмеченные изображения, ранжированные по неуверенности YOLO."""
    from services.ml_service import get_uncertainty_queue
    proj = (db.query(Project)
              .filter(Project.id == project_id).first())
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    limit = max(1, min(500, int(limit)))
    items = get_uncertainty_queue(db, project_id, limit=limit)
    return {"project_id": project_id, "limit": limit,
            "count": len(items), "items": items}


@router.post("/api/projects/{project_id}/streams")
def create_stream(project_id: int, payload: dict = Body(...),
                  db: Session = Depends(get_db)):
    """[FIX:v1341-backend] Создать RTSP-стрим с dedup + fps."""
    from models import Stream
    from services.stream_service import start_stream_worker
    proj = (db.query(Project)
              .filter(Project.id == project_id,
                      Project.is_deleted.is_(False)).first())
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    url = str((payload or {}).get("url", "")).strip()
    if not url:
        raise HTTPException(400, "Поле 'url' обязательно")
    name = str((payload or {}).get("name") or f"Stream {url[:40]}")
    try:
        fps = float((payload or {}).get("fps", 1.0))
    except (TypeError, ValueError):
        fps = 1.0
    fps = max(0.1, min(30.0, fps))
    # [PERF:rtsp-limit] Проверка лимита активных стримов
    active_count = db.query(Stream).filter(Stream.project_id == project_id, Stream.is_active == True).count()
    if active_count >= 2:
        raise HTTPException(400, "Достигнут лимит одновременных RTSP-стримов (макс. 2). Остановите другой стрим.")

    existing = (db.query(Stream)
                  .filter(Stream.project_id == project_id,
                          Stream.url == url).first())
    if existing:
        existing.is_active = True
        if name:
            existing.name = name
        existing.capture_fps = fps
        db.commit()
        db.refresh(existing)
        try:
            start_stream_worker(url, project_id, fps=fps,
                                stream_id=existing.id)
        except Exception as e:
            log_status("warning", "system", f"stream restart failed: {e}")
        return {"id": existing.id, "url": existing.url,
                "name": existing.name, "is_active": True,
                "worker": "restarted", "fps": fps}
    st = Stream(project_id=project_id, url=url, name=name,
                is_active=True, capture_fps=fps)
    db.add(st)
    db.commit()
    db.refresh(st)
    worker_status = "skipped"
    try:
        worker_status = start_stream_worker(
            url, project_id, fps=fps, stream_id=st.id).get("status", "started")
    except Exception as e:
        log_status("warning", "system", f"stream worker failed: {e}")
    return {"id": st.id, "url": st.url, "name": st.name,
            "is_active": True, "worker": worker_status, "fps": fps}


@router.get("/api/projects/{project_id}/streams")
def list_streams(project_id: int, db: Session = Depends(get_db)):
    from models import Stream
    rows = (db.query(Stream)
              .filter(Stream.project_id == project_id)
              .order_by(Stream.id.desc()).all())
    return [{"id": r.id, "url": r.url, "name": r.name,
             "is_active": bool(r.is_active),
             "fps": float(getattr(r, "capture_fps", 1.0) or 1.0)}
            for r in rows]


@router.post("/api/projects/{project_id}/behavior/train_classifier")
def train_behavior_clf(project_id: int, db: Session = Depends(get_db)):
    """Обучить RandomForest-классификатор поведения из текущей разметки."""
    from services.behavior_service import train_behavior_classifier
    proj = (db.query(Project)
              .filter(Project.id == project_id).first())
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                 "fallback": "Project not found"})
    result = train_behavior_classifier(db, project_id)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.post("/api/projects/{project_id}/streams/{stream_id}/stop")
def stop_stream(project_id: int, stream_id: int,
                db: Session = Depends(get_db)):
    """[FRONTEND:stream-stop] Остановить RTSP-воркер и пометить is_active=False."""
    from models import Stream
    from services.stream_service import stop_stream_worker
    st = (db.query(Stream)
            .filter(Stream.id == stream_id,
                    Stream.project_id == project_id).first())
    if not st:
        raise HTTPException(404, {"key": "error.streamNotFound",
                                 "fallback": "Stream not found"})
    try:
        stop_stream_worker(st.url, project_id)
    except Exception as e:
        log_status("warning", "system",
                   f"stop_stream_worker failed: {e}")
    st.is_active = False
    db.commit()
    return {"id": st.id, "is_active": False}
# [/FRONTEND:stream-stop]

# [/STAGE3:projects-extensions]


@router.get("/api/projects/{project_id}/behavior/classifier_meta")
def behavior_classifier_meta(project_id: int):
    """[FIX:v1341-backend] Мета обученного классификатора."""
    from services.behavior_service import get_behavior_classifier_meta
    m = get_behavior_classifier_meta(project_id)
    if not m:
        return {"exists": False}
    return m
# [FIX:v1341-backend]


# [STAGE3:PROJECTS-NEXT-AID]
@router.get("/api/projects/{project_id}/next_animal_id")
def next_animal_id(project_id: int, db: Session = Depends(get_db)):
    """Возвращает следующий свободный animal_id для проекта."""
    max_aid = (
        db.query(func.max(Annotation.animal_id))
          .join(ImageModel, Annotation.image_id == ImageModel.id)
          .filter(ImageModel.project_id == project_id,
                  ImageModel.is_deleted.is_(False),
                  Annotation.animal_id.isnot(None))
          .scalar() or 0
    )
    return {"next": int(max_aid) + 1}
# [/STAGE3:PROJECTS-NEXT-AID]
