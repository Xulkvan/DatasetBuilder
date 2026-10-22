from fastapi import APIRouter, HTTPException, Form, Depends, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from database import get_db
from models import Project, ImageModel, Tag, ImageTag
from logger import log_status
from schemas import BatchTagsIn, ProjectSettingsIn

router = APIRouter()

@router.get("/api/projects/{project_id}/tags")
def list_tags(project_id: int, db: Session = Depends(get_db)):
    tags = db.query(Tag).filter(Tag.project_id == project_id).order_by(Tag.name).all()
    tag_ids = [t.id for t in tags] or [0]
    counts = dict(db.query(ImageTag.tag_id, func.count(ImageTag.image_id)).join(ImageModel, ImageModel.id == ImageTag.image_id).filter(ImageTag.tag_id.in_(tag_ids), ImageModel.is_deleted.is_(False)).group_by(ImageTag.tag_id).all())
    return [{"id": t.id, "name": t.name, "color": t.color or "#0071e3", "count": int(counts.get(t.id, 0))} for t in tags]

@router.post("/api/projects/{project_id}/tags")
def create_tag(project_id: int, name: str = Form(...), color: str = Form("#0071e3"), db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj: raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    name = name.strip()
    if not name: raise HTTPException(400, {"key": "error.emptyTagName", "fallback": "Пустое имя тега"})
    if len(name) > 64: raise HTTPException(400, "Слишком длинное имя")
    if not (color or "").strip() or not color.startswith("#") or len(color) != 7:
        raise HTTPException(400, {"key": "error.invalidColor", "fallback": f"Некорректный цвет: {color!r}"})
    existing = db.query(Tag).filter(Tag.project_id == project_id, Tag.name == name).first()
    if existing: raise HTTPException(409, {"key": "error.tagExists", "fallback": "Такой тег уже существует"})
    t = Tag(project_id=project_id, name=name, color=color.lower())
    db.add(t); db.commit(); db.refresh(t)
    log_status("success", "tag", f"Создан тег «{name}»")
    return {"id": t.id, "name": t.name, "color": t.color, "count": 0}

@router.patch("/api/tags/{tag_id}")
def update_tag(tag_id: int, name: Optional[str] = Form(None), color: Optional[str] = Form(None), db: Session = Depends(get_db)):
    t = db.query(Tag).filter(Tag.id == tag_id).first()
    if not t: raise HTTPException(404, {"key": "error.tagNotFound", "fallback": "Tag not found"})
    if name is not None:
        nm = name.strip()
        if not nm: raise HTTPException(400, {"key": "error.emptyName", "fallback": "Пустое имя"})
        dup = db.query(Tag).filter(Tag.project_id == t.project_id, Tag.name == nm, Tag.id != t.id).first()
        if dup: raise HTTPException(409, {"key": "error.tagExists", "fallback": "Такой тег уже существует"})
        t.name = nm
    if color is not None:
        c = color.strip()
        if not c.startswith("#") or len(c) != 7: raise HTTPException(400, f"Некорректный цвет: {color!r}")
        t.color = c.lower()
    db.commit()
    return {"id": t.id, "name": t.name, "color": t.color}

@router.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    t = db.query(Tag).filter(Tag.id == tag_id).first()
    if not t: raise HTTPException(404, {"key": "error.tagNotFound", "fallback": "Tag not found"})
    db.query(ImageTag).filter(ImageTag.tag_id == tag_id).delete()
    db.delete(t); db.commit()
    log_status("warning", "tag", f"Удалён тег «{t.name}»")
    return {"status": "ok"}

@router.get("/api/images/{image_id}/tags")
def get_image_tags(image_id: int, db: Session = Depends(get_db)):
    rows = db.query(Tag).join(ImageTag, ImageTag.tag_id == Tag.id).filter(ImageTag.image_id == image_id).all()
    return [{"id": t.id, "name": t.name, "color": t.color or "#0071e3"} for t in rows]

@router.post("/api/images/{image_id}/tags")
def set_image_tags(image_id: int, tag_ids: list = Body(...), db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    db.query(ImageTag).filter(ImageTag.image_id == image_id).delete()
    for tid in tag_ids:
        t = db.query(Tag).filter(Tag.id == tid, Tag.project_id == img.project_id).first()
        if t: db.add(ImageTag(image_id=image_id, tag_id=tid))
    db.commit()
    return {"status": "ok", "count": len(tag_ids)}

@router.post("/api/images/batch_tags")
def batch_set_tags(payload: BatchTagsIn, db: Session = Depends(get_db)):
    if not payload.image_ids: return {"status": "ok", "updated": 0, "added": 0, "removed": 0}
    imgs = db.query(ImageModel).filter(ImageModel.id.in_(payload.image_ids)).all()
    if not imgs: raise HTTPException(404, "Изображения не найдены")
    project_ids = {im.project_id for im in imgs}
    if len(project_ids) > 1: raise HTTPException(400, "Изображения из разных проектов")
    pid = project_ids.pop()
    valid_add = [t.id for t in db.query(Tag).filter(Tag.id.in_(payload.add), Tag.project_id == pid).all()] if payload.add else []
    valid_remove = [t.id for t in db.query(Tag).filter(Tag.id.in_(payload.remove), Tag.project_id == pid).all()] if payload.remove else []
    if valid_remove: db.query(ImageTag).filter(ImageTag.image_id.in_(payload.image_ids), ImageTag.tag_id.in_(valid_remove)).delete(synchronize_session=False)
    if valid_add:
        existing_links = set((iid, tid) for iid, tid in db.query(ImageTag.image_id, ImageTag.tag_id).filter(ImageTag.image_id.in_(payload.image_ids), ImageTag.tag_id.in_(valid_add)).all())
        for im in imgs:
            for tid in valid_add:
                if (im.id, tid) not in existing_links: db.add(ImageTag(image_id=im.id, tag_id=tid))
    db.commit()
    return {"status": "ok", "updated": len(imgs), "added": len(valid_add), "removed": len(valid_remove)}
