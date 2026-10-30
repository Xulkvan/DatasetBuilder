import os
import re
import uuid
import sys
import subprocess
from collections import defaultdict
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Body, Form, Request  # [STAGE1-C:imports]
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, case, or_, text  # [PATCH:STAGE1_TEXT_IMPORT]

from database import get_db
from services.auth_service import get_current_user, require_permission
# [PATCH:RBAC_IMPORT]
from models import Project, ImageModel, Annotation, Keypoint, ImageTag
from schemas import AnnotationIn
from logger import utcnow, log_status
from config import UPLOAD_DIR, KEYPOINT_VALID, get_keypoint_schema_for_project # [PATCH:FIX_CUSTOM_KP_IMPORT]
from services.settings_service import get_trash_ttl_days
from services.image_service import (
    _remove_file_safe, _remove_thumb, _queue_thumb, ensure_thumb,
    _invalidate_stats_cache, find_duplicate, phash_hex, _invalidate_phash_index,
    _get_duplicate_ids_cached,
)
from services.file_service import (
    sanitize_display_name, validate_user_filename, make_unique_filename,
    _unique_name_mem, _detect_image_format, _open_image_safe, _split_name_ext, letterbox,
)
from services.rate_limiter import _limiter_upload, _rate_limit

router = APIRouter()

FIXED_SIZE = (640, 640)
LETTERBOX_FILL = (114, 114, 114)
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

@router.get("/api/projects/{project_id}/images")
def list_images(project_id: int, offset: int = 0, limit: int = 0, sort: str = "name_asc", filter: str = "none", search: str = "", tag_ids: str = "", my_tasks: bool = False, request: Request = None, db: Session = Depends(get_db)):
    parsed_tags = []
    if tag_ids:
        for t in tag_ids.split(","):
            try: parsed_tags.append(int(t.strip()))
            except (ValueError, TypeError): continue
    project_total = int(db.query(func.count(ImageModel.id)).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)).scalar() or 0)
    annotated_total = int(db.query(func.count(func.distinct(Annotation.image_id))).join(ImageModel, Annotation.image_id == ImageModel.id).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)).scalar() or 0)

    q = db.query(ImageModel).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False))
    if my_tasks and request:
        from services.auth_service import resolve_session
        u = request.cookies.get("pdb_session")
        if u:
            user = resolve_session(db, u)
            if user and user.get("id") and user["id"] > 0:
                q = q.filter(ImageModel.assigned_to == user["id"])
    if search: q = q.filter(ImageModel.filename.ilike(f"%{search}%"))
    if parsed_tags:
        tag_subq = db.query(ImageTag.image_id).filter(ImageTag.tag_id.in_(parsed_tags)).subquery()
        q = q.filter(ImageModel.id.in_(db.query(tag_subq.c.image_id)))
    if filter == "hard": q = q.filter(ImageModel.is_hard.is_(True))
    elif filter in ("unannotated", "lowconf"):
        stat_subq = db.query(Annotation.image_id.label("iid"), func.count(Annotation.id).label("cnt"), func.min(Annotation.confidence).label("min_conf")).group_by(Annotation.image_id).subquery()
        q = q.outerjoin(stat_subq, stat_subq.c.iid == ImageModel.id)
        if filter == "unannotated": q = q.filter(or_(stat_subq.c.cnt.is_(None), stat_subq.c.cnt == 0))
        else: q = q.filter(stat_subq.c.min_conf < 0.5)
    elif filter == "duplicates":
        dup_ids = _get_duplicate_ids_cached(project_id, db)
        q = q.filter(ImageModel.id.in_(list(dup_ids))) if dup_ids else q.filter(ImageModel.id.in_([-1]))

    filtered_total = int(q.count())
    # [PERF:server-sort]
    if sort == "name_asc": q = q.order_by(ImageModel.filename.asc())
    elif sort == "name_desc": q = q.order_by(ImageModel.filename.desc())
    elif sort == "type_asc": q = q.order_by(ImageModel.filename.asc())
    elif sort == "type_desc": q = q.order_by(ImageModel.filename.desc())
    elif sort == "date_asc": q = q.order_by(ImageModel.created_at.asc())
    elif sort == "date_desc": q = q.order_by(ImageModel.created_at.desc())
    elif sort == "size_asc": q = q.order_by(ImageModel.file_size.asc())
    elif sort == "size_desc": q = q.order_by(ImageModel.file_size.desc())
    else: q = q.order_by(ImageModel.id.asc())

    # [PERF:cap-2000]
    if limit > 0: rows = q.offset(max(0, offset)).limit(min(limit, 2000)).all()
    else: rows = q.limit(2000).all()

    ids = [r.id for r in rows] or [0]
    raw_stats = db.query(Annotation.image_id.label("iid"), func.count(Annotation.id).label("cnt"), func.min(Annotation.confidence).label("min_conf"), func.avg(Annotation.confidence).label("avg_conf"), func.sum(case((Annotation.confidence < 0.5, 1), else_=0)).label("low_cnt")).filter(Annotation.image_id.in_(ids)).group_by(Annotation.image_id).all()
    stats = {s.iid: {"cnt": int(s.cnt or 0), "min_conf": float(s.min_conf) if s.min_conf is not None else None, "avg_conf": float(s.avg_conf) if s.avg_conf is not None else None, "low_cnt": int(s.low_cnt or 0)} for s in raw_stats}

    beh_rows = db.query(Annotation.image_id, Annotation.behavior).filter(Annotation.image_id.in_(ids), Annotation.behavior.isnot(None)).distinct().all()
    behaviors_map = defaultdict(set)
    for iid, beh in beh_rows: behaviors_map[iid].add(beh)

    tag_map = defaultdict(list)
    for it in db.query(ImageTag.image_id, ImageTag.tag_id).filter(ImageTag.image_id.in_(ids)).all(): tag_map[it.image_id].append(it.tag_id)

    items = [{"id": r.id, "filename": r.filename, "width": r.width, "height": r.height, "annotation_count": stats.get(r.id, {}).get("cnt", 0), "is_deleted": False, "is_hard": bool(r.is_hard), "min_confidence": stats.get(r.id, {}).get("min_conf"), "avg_confidence": stats.get(r.id, {}).get("avg_conf"), "low_conf_count": stats.get(r.id, {}).get("low_cnt", 0), "tag_ids": tag_map.get(r.id, []), "video_id": r.video_id, "frame_index": r.frame_index, "created_at": r.created_at.isoformat() if r.created_at else None, "file_size": r.file_size, "timestamp_sec": r.timestamp_sec, "behaviors": sorted(list(behaviors_map.get(r.id, [])))} for r in rows]

    if limit == 0: return items
    return {"items": items, "total": filtered_total, "offset": offset, "limit": limit, "project_total": project_total, "annotated_total": annotated_total}

@router.get("/api/projects/{project_id}/trash")
def list_trash(project_id: int, db: Session = Depends(get_db)):
    rows = db.query(ImageModel).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(True)).order_by(ImageModel.deleted_at.desc(), ImageModel.id.desc()).all()
    ttl = get_trash_ttl_days(db)
    proj = db.query(Project).filter(Project.id == project_id).first()
    if proj and proj.trash_ttl_days_override is not None: ttl = proj.trash_ttl_days_override
    now = utcnow()
    return [{"id": r.id, "filename": r.filename, "width": r.width, "height": r.height, "is_deleted": True, "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None, "days_left": max(0, (r.deleted_at + timedelta(days=ttl) - now).days) if r.deleted_at and ttl > 0 else None} for r in rows]

@router.post("/api/projects/{project_id}/images")
def upload_image(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _rate_limit(_limiter_upload, "local", {"key": "error.rateLimited", "fallback": "Слишком много запросов."})
    proj = db.query(Project).filter(Project.id == project_id, Project.is_deleted.is_(False)).first()
    if not proj: raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})

    content_length = file.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES: raise HTTPException(413, f"Файл больше {MAX_UPLOAD_BYTES // (1024*1024)} МБ")
        except (ValueError, TypeError): pass

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES: raise HTTPException(413, "Файл слишком большой")
    fmt = _detect_image_format(data)
    if not fmt: raise HTTPException(400, "Unsupported image format")

    img = _open_image_safe(data).convert("RGB")
    img = letterbox(img, FIXED_SIZE, LETTERBOX_FILL)
    fname = f"{uuid.uuid4().hex}.jpg"
    path = os.path.join(UPLOAD_DIR, fname)
    img.save(path, "JPEG", quality=95)

    try: ph = phash_hex(path)
    except Exception: ph = ""

    dup = find_duplicate(db, project_id, ph)
    if dup:
        _remove_file_safe(path)
        raise HTTPException(409, f"Дубликат: похоже на «{dup.filename}»")

    original_name = sanitize_display_name(file.filename or fname, fallback=fname)
    unique_name = make_unique_filename(db, project_id, original_name)
    try: fsize = os.path.getsize(path)
    except OSError: fsize = len(data)

    im = ImageModel(project_id=project_id, filename=unique_name, path=path, width=FIXED_SIZE[0], height=FIXED_SIZE[1], is_deleted=False, phash=ph or None, is_hard=False, created_at=utcnow(), file_size=fsize)
    db.add(im); db.commit(); db.refresh(im)
    _queue_thumb(im.id, im.path); _invalidate_stats_cache(project_id); _invalidate_phash_index(project_id)
    # [FIX:v1341-backend]
    try:
        from services.auto_blur_service import schedule_auto_blur
        schedule_auto_blur(im.id, project_id)
    except Exception:
        pass

    return {"id": im.id, "filename": im.filename, "width": im.width, "height": im.height, "annotation_count": 0, "is_deleted": False, "is_hard": False, "renamed_from": original_name if unique_name != original_name else None}

@router.post("/api/images/{image_id}/rename")
def rename_image(image_id: int, filename: str = Form(...), db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    raw = (filename or "").strip()
    validate_user_filename(raw)
    _, old_ext = _split_name_ext(img.filename)
    new_base, _ = _split_name_ext(raw)
    new_base = new_base.strip().rstrip('.')
    if not new_base: raise HTTPException(400, {"key": "error.emptyStem", "fallback": "Пустое имя файла"})
    new_name = new_base + (old_ext or '')
    if len(new_name) > 255: raise HTTPException(400, "Слишком длинное имя (макс. 255)")
    conflict = db.query(ImageModel).filter(ImageModel.project_id == img.project_id, ImageModel.is_deleted.is_(False), ImageModel.id != img.id, ImageModel.filename == new_name).first()
    if conflict: raise HTTPException(409, f"Имя «{new_name}» уже занято")
    img.filename = new_name; db.commit()
    return {"id": img.id, "filename": img.filename}

@router.post("/api/images/{image_id}/toggle_hard")
def toggle_hard(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    img.is_hard = not bool(img.is_hard); db.commit()
    return {"id": img.id, "is_hard": bool(img.is_hard)}

@router.post("/api/images/{image_id}/reveal")
def reveal_image(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    if not os.path.exists(img.path): raise HTTPException(404, {"key": "error.fileMissing", "fallback": "Файл отсутствует"})
    if os.name == "nt": subprocess.Popen(["explorer", "/select,", os.path.normpath(img.path)])
    elif sys.platform == "darwin": subprocess.Popen(["open", "-R", img.path])
    else: subprocess.Popen(["xdg-open", os.path.dirname(img.path)])
    return {"status": "ok"}

@router.get("/api/images/{image_id}/thumb",
            dependencies=[Depends(require_permission("annotation.write"))])  # [PATCH:STAGE2-IDOR-IMAGES]
def get_image_thumb(image_id: int, db: Session = Depends(get_db)):
    row = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not row: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    p = ensure_thumb(row.id, row.path)
    if not p or not os.path.exists(p): raise HTTPException(500, "Cannot generate thumbnail")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

# [STAGE6:blur-cache]
_BLUR_CACHE: dict = {}
_BLUR_CACHE_LOCK = __import__('threading').Lock()
_BLUR_CACHE_MAX = 32


def _blur_cache_get(image_id, path, regions):
    import hashlib, os
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    rs = ",".join(
        f"{r.x:.4f}:{r.y:.4f}:{r.w:.4f}:{r.h:.4f}"
        for r in sorted(regions, key=lambda x: (x.x, x.y, x.w, x.h))
    )
    key = hashlib.md5(f"{image_id}|{mtime}|{rs}".encode()).hexdigest()
    with _BLUR_CACHE_LOCK:
        return _BLUR_CACHE.get(key)


def _blur_cache_put(image_id, path, regions, data: bytes) -> None:
    import hashlib, os
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    rs = ",".join(
        f"{r.x:.4f}:{r.y:.4f}:{r.w:.4f}:{r.h:.4f}"
        for r in sorted(regions, key=lambda x: (x.x, x.y, x.w, x.h))
    )
    key = hashlib.md5(f"{image_id}|{mtime}|{rs}".encode()).hexdigest()
    with _BLUR_CACHE_LOCK:
        if len(_BLUR_CACHE) >= _BLUR_CACHE_MAX:
            _BLUR_CACHE.pop(next(iter(_BLUR_CACHE)))
        _BLUR_CACHE[key] = data


@router.get("/api/images/{image_id}/file",
            dependencies=[Depends(require_permission("annotation.write"))])  # [PATCH:STAGE2-IDOR-IMAGES]
def get_image_file(image_id: int, db: Session = Depends(get_db)):
    row = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not row: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    if not row.path or not os.path.exists(row.path):
        fname = os.path.basename(row.path) if row.path else ""
        alt_path = os.path.join(UPLOAD_DIR, fname) if fname else ""
        if alt_path and os.path.exists(alt_path):
            row.path = alt_path; db.commit(); return FileResponse(alt_path)
        raise HTTPException(404, {"key": "error.fileMissing", "fallback": "Файл отсутствует"})
    # [STAGE2:blur-render]
    try:
        from models import BlurRegion
        blur = db.query(BlurRegion).filter(
            BlurRegion.image_id == image_id).all()
        if blur:
            from fastapi.responses import Response as _Resp
            _cached = _blur_cache_get(image_id, row.path, blur)
            if _cached is not None:
                return _Resp(content=_cached, media_type="image/jpeg")
            from PIL import Image as _PILImage, ImageFilter as _PILFilter
            from io import BytesIO as _BytesIO
            im = _PILImage.open(row.path)
            W, H = im.size
            for r in blur:
                x1 = max(0, int(r.x * W)); y1 = max(0, int(r.y * H))
                x2 = min(W, int((r.x + r.w) * W))
                y2 = min(H, int((r.y + r.h) * H))
                if x2 <= x1 or y2 <= y1:
                    continue
                region = im.crop((x1, y1, x2, y2)).filter(
                    _PILFilter.GaussianBlur(radius=14))
                im.paste(region, (x1, y1))
            buf = _BytesIO()
            fmt = "JPEG" if row.path.lower().endswith((".jpg", ".jpeg")) else "PNG"
            im.save(buf, format=fmt, quality=92)
            _data = buf.getvalue()
            _blur_cache_put(image_id, row.path, blur, _data)
            return _Resp(content=_data,
                         media_type="image/jpeg" if fmt == "JPEG" else "image/png")
    except Exception:
        pass
    return FileResponse(row.path)

@router.delete("/api/images/{image_id}", dependencies=[Depends(require_permission("image.delete"))])
def soft_delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    if img.is_deleted: return {"status": "ok", "deleted_id": image_id, "soft": True, "already_deleted": True}
    img.is_deleted = True; img.deleted_at = utcnow(); db.commit()
    _invalidate_stats_cache(img.project_id)
    _invalidate_phash_index(img.project_id)
    return {"status": "ok", "deleted_id": image_id, "soft": True}

@router.delete("/api/images/{image_id}/permanent")
def permanent_delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    file_path = img.path; pid = img.project_id
    db.delete(img); db.commit()
    _remove_file_safe(file_path); _remove_thumb(image_id)
    _invalidate_phash_index(pid)
    _invalidate_stats_cache(pid)
    return {"status": "ok", "deleted_id": image_id, "permanent": True}

@router.post("/api/images/batch_delete", dependencies=[Depends(require_permission("image.delete"))])
def batch_delete_images(ids: list = Body(...), db: Session = Depends(get_db)):
    if not ids: return {"deleted": 0}
    now = utcnow(); rows = db.query(ImageModel).filter(ImageModel.id.in_(ids)).all()
    changed = 0
    for r in rows:
        if r.is_deleted: continue
        r.is_deleted = True; r.deleted_at = now; changed += 1
    db.commit()
    if rows:
        pids = {r.project_id for r in rows}
        for pid in pids:
            _invalidate_phash_index(pid)
            _invalidate_stats_cache(pid)
    return {"deleted": changed, "ids": [r.id for r in rows]}

@router.post("/api/images/batch_restore")
def batch_restore_images(ids: list = Body(...), db: Session = Depends(get_db)):
    if not ids: return {"restored": 0, "renamed": 0}
    rows = db.query(ImageModel).filter(ImageModel.id.in_(ids)).all()
    by_project = defaultdict(set); pending = defaultdict(set); total_renamed = 0; restored_count = 0; restored_ids = []
    for r in rows:
        if not r.is_deleted: continue
        restored_count += 1; restored_ids.append(r.id); pid = r.project_id
        if pid not in by_project:
            used = {n for (n,) in db.query(ImageModel.filename).filter(ImageModel.project_id == pid, ImageModel.is_deleted.is_(False)).all()}
            by_project[pid] = used
        used = by_project[pid] | pending[pid]; new_name = r.filename
        if new_name in used:
            base, ext = _split_name_ext(new_name)
            m = re.match(r'^(.*) \(\d+\)$', base)
            base_root = m.group(1) if m else base
            max_n = 0
            for ex in used:
                e_base, e_ext = _split_name_ext(ex)
                if e_ext.lower() != ext.lower(): continue
                m2 = re.match(r'^' + re.escape(base_root) + r' \(\d+\)$', e_base)
                if m2: max_n = max(max_n, int(m2.group(1)))
            new_name = f"{base_root} ({max_n + 1}){ext}"
            total_renamed += 1
        pending[pid].add(new_name); r.filename = new_name; r.is_deleted = False; r.deleted_at = None
    db.commit()
    pids = {r.project_id for r in rows}
    for pid in pids:
        _invalidate_phash_index(pid)
        _invalidate_stats_cache(pid)
    return {"restored": restored_count, "renamed": total_renamed, "ids": restored_ids}

@router.post("/api/images/batch_permanent_delete", dependencies=[Depends(require_permission("image.delete"))])
def batch_permanent_delete_images(ids: list = Body(...), db: Session = Depends(get_db)):
    if not ids: return {"deleted": 0}
    rows = db.query(ImageModel).filter(ImageModel.id.in_(ids)).all()
    paths = [r.path for r in rows]
    for r in rows: db.delete(r)
    pids = {r.project_id for r in rows}
    db.commit()
    for p in paths: _remove_file_safe(p)
    for iid in ids: _remove_thumb(iid)
    for pid in pids:
        _invalidate_phash_index(pid)
        _invalidate_stats_cache(pid)
    return {"deleted": len(rows), "ids": ids}

@router.post("/api/projects/{project_id}/trash/empty")
def empty_trash(project_id: int, db: Session = Depends(get_db)):
    rows = db.query(ImageModel).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(True)).all()
    paths = [r.path for r in rows]; ids = [r.id for r in rows]
    for r in rows: db.delete(r)
    db.commit()
    for p in paths: _remove_file_safe(p)
    for iid in ids: _remove_thumb(iid)
    _invalidate_phash_index(project_id)
    _invalidate_stats_cache(project_id)
    log_status("warning", "trash", f"Корзина проекта #{project_id} очищена: {len(rows)}")
    return {"status": "ok", "deleted": len(rows)}

@router.post("/api/images/{image_id}/restore")
def restore_image(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    if not img.is_deleted: return {"status": "ok", "restored_id": image_id, "filename": img.filename, "already_active": True}
    img.filename = make_unique_filename(db, img.project_id, img.filename, exclude_id=img.id)
    img.is_deleted = False; img.deleted_at = None; db.commit()
    return {"status": "ok", "restored_id": image_id, "filename": img.filename}

@router.get("/api/images/{image_id}/annotations",
            dependencies=[Depends(require_permission("annotation.write"))])  # [PATCH:STAGE2-IDOR-IMAGES]
def get_annotations(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    rows = db.query(Annotation).filter(Annotation.image_id == image_id).order_by(Annotation.id).all()
    ann_ids = [a.id for a in rows]
    kps_by_ann = defaultdict(list)
    if ann_ids:
        for kp in db.query(Keypoint).filter(Keypoint.annotation_id.in_(ann_ids)).all():
            kps_by_ann[kp.annotation_id].append({"name": kp.name, "x": kp.x, "y": kp.y, "visibility": kp.visibility})
    return [{"id": a.id, "x": a.x, "y": a.y, "w": a.w, "h": a.h, "label": a.label, "confidence": a.confidence, "frozen": bool(a.is_frozen), "behavior": a.behavior, "animal_id": a.animal_id, "keypoints": kps_by_ann.get(a.id, [])} for a in rows]

@router.post("/api/images/{image_id}/annotations", dependencies=[Depends(require_permission("annotation.write"))])
def save_annotations(image_id: int, annotations: list[AnnotationIn], db: Session = Depends(get_db)):
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img: raise HTTPException(404, {"key": "error.imageNotFound", "fallback": "Image not found"})
    # [STAGE1-A:save-atomic] block concurrent edits
    try:
        db.execute(text("SELECT id FROM images WHERE id=:iid FOR UPDATE"), {"iid": image_id})
    except Exception:
        pass  # MySQL only; SQLite ignores FOR UPDATE, atomicity handled by WAL
    old_ids = [row.id for row in db.query(Annotation.id).filter(Annotation.image_id == image_id).all()]
    schema = get_keypoint_schema_for_project(db, img.project_id)
    valid_names = frozenset(k[0] for k in schema) # [PATCH:FIX_CUSTOM_KP_VALID] # [PATCH:FIX_CUSTOM_KP_VALID]
    if old_ids: db.query(Keypoint).filter(Keypoint.annotation_id.in_(old_ids)).delete(synchronize_session=False)
    db.query(Annotation).filter(Annotation.image_id == image_id).delete()
    new_anns = []
    for a in annotations:
        ann = Annotation(image_id=image_id, x=a.x, y=a.y, w=a.w, h=a.h, label=a.label, confidence=a.confidence, is_frozen=bool(a.frozen), behavior=a.behavior, animal_id=a.animal_id, behavior_source=getattr(a, "behavior_source", None))  # [STAGE2:behavior-source-save]
        db.add(ann); new_anns.append((ann, getattr(a, 'keypoints', [])))
    db.flush()
    for ann, kps in new_anns:
        seen = set()
        for kp in kps:
            try:
                nm = str(kp.get("name", "")).strip()
                if not nm or nm not in valid_names or nm in seen: continue
                x = max(0.0, min(1.0, float(kp.get("x", 0)))); y = max(0.0, min(1.0, float(kp.get("y", 0)))); vis = max(0.0, min(1.0, float(kp.get("visibility", 1.0))))
                db.add(Keypoint(annotation_id=ann.id, name=nm, x=x, y=y, visibility=vis)); seen.add(nm)
            except (TypeError, ValueError): continue
    db.commit(); _invalidate_stats_cache(img.project_id)
    # [STAGE1:webhook-ann-saved]
    try:
        from services.webhook_service import dispatch_event as _wh_dispatch
        _wh_dispatch(db, img.project_id, "annotation.saved",
                     {"image_id": image_id, "count": len(annotations)})
    except Exception:
        pass
    return {"status": "ok", "count": len(annotations)}


# [STAGE1-B:track-merge]
@router.post("/api/projects/{project_id}/tracks/merge")
def merge_tracks(project_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    src_ids = payload.get("source_animal_ids") or []
    target = payload.get("target_animal_id")
    if not src_ids or target is None:
        raise HTTPException(400, "source_animal_ids и target_animal_id обязательны")
    ids_subq = db.query(ImageModel.id).filter(ImageModel.project_id == project_id,
                                              ImageModel.is_deleted.is_(False)).subquery()
    n = (db.query(Annotation)
           .filter(Annotation.image_id.in_(db.query(ids_subq.c.id)),
                   Annotation.animal_id.in_(src_ids))
           .update({Annotation.animal_id: int(target)}, synchronize_session=False))
    db.commit()
    log_status("info", "video", f"tracks merge: {src_ids} → {target}, обновлено {n}")
    return {"updated": int(n), "target": int(target)}


# [STAGE1-B:track-reassign]
@router.post("/api/projects/{project_id}/tracks/reassign")
def reassign_track(project_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    old = payload.get("old_animal_id")
    new = payload.get("new_animal_id")
    if old is None or new is None:
        raise HTTPException(400, "old_animal_id и new_animal_id обязательны")
    ids_subq = db.query(ImageModel.id).filter(ImageModel.project_id == project_id,
                                              ImageModel.is_deleted.is_(False)).subquery()
    n = (db.query(Annotation)
           .filter(Annotation.image_id.in_(db.query(ids_subq.c.id)),
                   Annotation.animal_id == int(old))
           .update({Annotation.animal_id: int(new)}, synchronize_session=False))
    db.commit()
    return {"updated": int(n), "old": int(old), "new": int(new)}


# [STAGE1-B:track-delete]
@router.delete("/api/projects/{project_id}/tracks/{animal_id}")
def delete_track(project_id: int, animal_id: int, db: Session = Depends(get_db)):
    ids_subq = db.query(ImageModel.id).filter(ImageModel.project_id == project_id,
                                              ImageModel.is_deleted.is_(False)).subquery()
    n = (db.query(Annotation)
           .filter(Annotation.image_id.in_(db.query(ids_subq.c.id)),
                   Annotation.animal_id == int(animal_id))
           .update({Annotation.animal_id: None}, synchronize_session=False))
    db.commit()
    return {"cleared": int(n), "animal_id": int(animal_id)}


# [STAGE1-C:video-stream]
@router.get("/api/videos/{video_id}/stream")
def stream_video(video_id: int, request: Request, db: Session = Depends(get_db)):
    """Range-aware отдача видеофайла для <video>."""
    from models import Video
    from fastapi.responses import StreamingResponse
    import os as _os
    v = db.query(Video).filter(Video.id == video_id, Video.is_deleted.is_(False)).first()
    if not v or not _os.path.exists(v.path):
        raise HTTPException(404, {"key": "error.videoNotFound", "fallback": "Video not found"})
    fsize = _os.path.getsize(v.path)
    range_header = request.headers.get("range", "")
    start, end = 0, fsize - 1
    if range_header.startswith("bytes="):
        try:
            rng = range_header[6:].split("-")
            start = int(rng[0]) if rng[0] else 0
            end = int(rng[1]) if len(rng) > 1 and rng[1] else fsize - 1
        except ValueError:
            pass
    end = min(end, fsize - 1)
    length = end - start + 1
    def iterfile():
        with open(v.path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk: break
                remaining -= len(chunk)
                yield chunk
    headers = {
        "Content-Range": f"bytes {start}-{end}/{fsize}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    }
    status_code = 206 if range_header else 200
    return StreamingResponse(iterfile(), status_code=status_code, headers=headers,
                             media_type="video/mp4")


# [STAGE1-C:video-batch-ann]
@router.get("/api/videos/{video_id}/frame_annotations")
def video_frame_annotations(video_id: int, from_frame: int = 0, to_frame: int = 999999,
                             db: Session = Depends(get_db)):
    """Батч: {frame_index: [{ann...}]} для всех кадров видео."""
    from models import Video
    v = db.query(Video).filter(Video.id == video_id).first()
    if not v:
        raise HTTPException(404, {"key": "error.videoNotFound", "fallback": "Video not found"})
    rows = (db.query(ImageModel.frame_index, Annotation, ImageModel.id)
              .join(Annotation, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.video_id == video_id, ImageModel.is_deleted.is_(False),
                      ImageModel.frame_index >= from_frame, ImageModel.frame_index <= to_frame)
              .order_by(ImageModel.frame_index, Annotation.id)
              .all())
    out = {}
    for fidx, a, iid in rows:
        key = str(fidx or 0)
        out.setdefault(key, []).append({
            "ann_id": a.id, "image_id": iid,
            "x": a.x, "y": a.y, "w": a.w, "h": a.h,
            "label": a.label, "behavior": a.behavior, "animal_id": a.animal_id,
            "confidence": a.confidence,
        })
    return {"video_id": video_id, "frames": out}


# [STAGE1-C:interpolate]
@router.post("/api/projects/{project_id}/interpolate")
def interpolate_track(project_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Интерполирует bbox и keypoints между двумя ключевыми кадрами."""
    from models import Keypoint
    aid = payload.get("animal_id")
    if aid is None:
        raise HTTPException(400, "animal_id обязателен")
    a = db.query(Annotation).filter(Annotation.id == payload.get("from_ann_id")).first() if payload.get("from_ann_id") else None
    b = db.query(Annotation).filter(Annotation.id == payload.get("to_ann_id")).first() if payload.get("to_ann_id") else None
    if a is None or b is None:
        raise HTTPException(400, "Нужны from_ann_id и to_ann_id существующих рамок")
    a_img = db.query(ImageModel).filter(ImageModel.id == a.image_id).first()
    b_img = db.query(ImageModel).filter(ImageModel.id == b.image_id).first()
    if not a_img or not b_img or a_img.video_id != b_img.video_id:
        raise HTTPException(400, "Кадры должны быть из одного видео")
    f1, f2 = a_img.frame_index or 0, b_img.frame_index or 0
    if f2 <= f1:
        raise HTTPException(400, "from_frame должен быть < to_frame")
    mids = (db.query(ImageModel)
              .filter(ImageModel.video_id == a_img.video_id,
                      ImageModel.frame_index > f1, ImageModel.frame_index < f2,
                      ImageModel.is_deleted.is_(False))
              .order_by(ImageModel.frame_index).all())
    a_kps = {k.name: k for k in db.query(Keypoint).filter(Keypoint.annotation_id == a.id).all()}
    b_kps = {k.name: k for k in db.query(Keypoint).filter(Keypoint.annotation_id == b.id).all()}
    common_names = set(a_kps.keys()) & set(b_kps.keys())
    created = 0
    for mid in mids:
        t = (mid.frame_index - f1) / (f2 - f1)
        existing = (db.query(Annotation)
                      .filter(Annotation.image_id == mid.id, Annotation.animal_id == int(aid))
                      .first())
        nx = a.x + (b.x - a.x) * t
        ny = a.y + (b.y - a.y) * t
        nw = a.w + (b.w - a.w) * t
        nh = a.h + (b.h - a.h) * t
        if existing:
            existing.x, existing.y, existing.w, existing.h = nx, ny, nw, nh
            new_ann = existing
        else:
            new_ann = Annotation(image_id=mid.id, x=nx, y=ny, w=nw, h=nh,
                                 label=a.label, confidence=None, is_frozen=False,
                                 behavior=a.behavior, animal_id=int(aid))
            db.add(new_ann); db.flush()
        if common_names:
            existing_kps = {k.name: k for k in db.query(Keypoint).filter(Keypoint.annotation_id == new_ann.id).all()}
            for nm in common_names:
                ka, kb = a_kps[nm], b_kps[nm]
                kx = ka.x + (kb.x - ka.x) * t
                ky = ka.y + (kb.y - ka.y) * t
                kv = 1.0 if (ka.visibility or 0) >= 0.5 and (kb.visibility or 0) >= 0.5 else 0.0
                if nm in existing_kps:
                    ek = existing_kps[nm]
                    ek.x, ek.y, ek.visibility = kx, ky, kv
                else:
                    db.add(Keypoint(annotation_id=new_ann.id, name=nm, x=kx, y=ky, visibility=kv))
        created += 1
    db.commit()
    return {"interpolated_frames": created, "animal_id": int(aid),
            "from_frame": f1, "to_frame": f2}



# [STAGE2:blur-regions]
from pydantic import BaseModel as _PydB


class BlurRegionIn(_PydB):
    x: float
    y: float
    w: float
    h: float


@router.post("/api/images/{image_id}/blur_regions")
def set_blur_regions(image_id: int, payload: list[BlurRegionIn] = Body(...),
                     db: Session = Depends(get_db)):
    from models import BlurRegion
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound",
                                 "fallback": "Image not found"})
    db.query(BlurRegion).filter(BlurRegion.image_id == image_id).delete()
    for r in payload:
        x = max(0.0, min(1.0, float(r.x)))
        y = max(0.0, min(1.0, float(r.y)))
        w = max(0.001, min(1.0, float(r.w)))
        h = max(0.001, min(1.0, float(r.h)))
        db.add(BlurRegion(image_id=image_id, x=x, y=y, w=w, h=h))
    db.commit()
    return {"status": "ok", "count": len(payload)}


@router.get("/api/images/{image_id}/blur_regions")
def get_blur_regions(image_id: int, db: Session = Depends(get_db)):
    from models import BlurRegion
    rows = (db.query(BlurRegion)
              .filter(BlurRegion.image_id == image_id).all())
    return [{"x": r.x, "y": r.y, "w": r.w, "h": r.h} for r in rows]


@router.delete("/api/images/{image_id}/blur_regions")
def clear_blur_regions(image_id: int, db: Session = Depends(get_db)):
    from models import BlurRegion
    db.query(BlurRegion).filter(BlurRegion.image_id == image_id).delete()
    db.commit()
    return {"status": "ok"}

# [FIX:v1341-backend]
