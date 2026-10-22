from fastapi import APIRouter, HTTPException, Form, Depends
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
    return {"id": proj.id, "name": proj.name, "object_class": proj.object_class or "pig", "object_class_source": proj.object_class_source or "list", "images_count": int(images_count), "annotations_count": int(ann_count), "is_deleted": bool(proj.is_deleted), "trash_ttl_days_override": proj.trash_ttl_days_override, "thumbnail_size": proj.thumbnail_size, "default_zoom": proj.default_zoom, "global_trash_ttl": get_trash_ttl_days(db)}

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
    return get_project_stats_cached(project_id, db)
