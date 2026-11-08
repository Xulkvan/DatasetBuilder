"""routers/tracks.py — Stage 3.11 (tracks list / motion vectors / navigate)."""
import csv
import json
from collections import defaultdict
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from services.auth_service import get_current_user
from services.project_access import check_project_access, check_image_access
from models import Project, ImageModel, Annotation
from services.image_service import _iou_xywh
from services.motion_service import _check_motion_batch
from logger import utcnow

router = APIRouter()


@router.get("/api/projects/{project_id}/tracks")
def list_project_tracks(project_id: int, user: dict = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    rows = (db.query(Annotation.animal_id,
                     func.count(func.distinct(ImageModel.id)).label("frames_count"),
                     func.min(ImageModel.id).label("first_image_id"))
              .join(ImageModel, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False),
                      Annotation.animal_id.isnot(None))
              .group_by(Annotation.animal_id)
              .order_by(Annotation.animal_id).all())
    if not rows:
        return {"items": [], "total": 0}
    first_ids = [int(r.first_image_id) for r in rows if r.first_image_id]
    first_imgs = {}
    if first_ids:
        first_imgs = {iid: fname for iid, fname in
                      db.query(ImageModel.id, ImageModel.filename)
                        .filter(ImageModel.id.in_(first_ids)).all()}
    beh_rows = (db.query(Annotation.animal_id, Annotation.behavior,
                         func.count(Annotation.id).label("cnt"))
                  .join(ImageModel, Annotation.image_id == ImageModel.id)
                  .filter(ImageModel.project_id == project_id,
                          ImageModel.is_deleted.is_(False),
                          Annotation.animal_id.isnot(None),
                          Annotation.behavior.isnot(None))
                  .group_by(Annotation.animal_id, Annotation.behavior).all())
    top_beh, _best_cnt = {}, {}
    for aid, beh, cnt in beh_rows:
        aid = int(aid); cnt = int(cnt or 0)
        if cnt > _best_cnt.get(aid, 0):
            _best_cnt[aid] = cnt; top_beh[aid] = beh
    out = []
    for r in rows:
        aid = int(r.animal_id)
        first_id = int(r.first_image_id) if r.first_image_id else None
        out.append({"animal_id": aid, "frames_count": int(r.frames_count or 0),
                    "first_image_id": first_id,
                    "first_filename": first_imgs.get(first_id),
                    "top_behavior": top_beh.get(aid)})
    return {"items": out, "total": len(out)}


@router.post("/api/images/{image_id}/link_from_prev")
def link_from_prev(image_id: int, iou_threshold: float = 0.5,
                   user: dict = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    check_image_access(db, image_id, user)
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
    if img.video_id is None or img.frame_index is None:
        raise HTTPException(400, "У этого изображения нет video_id / frame_index")
    prev_img = (db.query(ImageModel)
                  .filter(ImageModel.video_id == img.video_id,
                          ImageModel.frame_index < img.frame_index,
                          ImageModel.is_deleted.is_(False))
                  .order_by(ImageModel.frame_index.desc()).first())
    if not prev_img:
        return {"linked": 0, "reason": "no_prev_frame"}
    prev_anns = (db.query(Annotation)
                   .filter(Annotation.image_id == prev_img.id,
                           Annotation.animal_id.isnot(None)).all())
    if not prev_anns:
        return {"linked": 0, "reason": "no_aid_on_prev"}
    cur_anns = (db.query(Annotation).filter(Annotation.image_id == img.id).all())
    linked, details = 0, []
    for a in cur_anns:
        best, best_iou = None, 0.0
        for p in prev_anns:
            iou = _iou_xywh(
                {"x": a.x, "y": a.y, "w": a.w, "h": a.h},
                {"x": p.x, "y": p.y, "w": p.w, "h": p.h})
            if iou > best_iou:
                best_iou, best = iou, p
        if best is None or best_iou < iou_threshold:
            continue
        if a.animal_id == best.animal_id:
            continue
        old_aid = a.animal_id
        a.animal_id = best.animal_id
        linked += 1
        details.append({"ann_id": a.id, "old_animal_id": old_aid,
                        "new_animal_id": int(best.animal_id),
                        "iou": round(best_iou, 3)})
    if linked:
        db.commit()
    return {"linked": linked, "prev_image_id": prev_img.id,
            "details": details}


@router.get("/api/projects/{project_id}/navigate_with_aid")
def navigate_with_aid(project_id: int, from_image_id: int, animal_id: int,
                      dir: str = "next",
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    img = db.query(ImageModel).filter(ImageModel.id == from_image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
    if img.video_id is None or img.frame_index is None:
        return {"found": False, "reason": "no_video"}
    d = (dir or "next").lower()
    q = (db.query(ImageModel.id, ImageModel.frame_index)
           .join(Annotation, Annotation.image_id == ImageModel.id)
           .filter(ImageModel.project_id == project_id,
                   ImageModel.video_id == img.video_id,
                   ImageModel.is_deleted.is_(False),
                   Annotation.animal_id == int(animal_id),
                   ImageModel.id != img.id))
    if d == "prev":
        q = q.filter(ImageModel.frame_index < img.frame_index)                          .order_by(ImageModel.frame_index.desc())
    else:
        q = q.filter(ImageModel.frame_index > img.frame_index)                          .order_by(ImageModel.frame_index.asc())
    row = q.first()
    if not row:
        return {"found": False, "reason": "end_of_track"}
    return {"found": True, "image_id": int(row.id),
            "frame_index": int(row.frame_index)}


@router.get("/api/projects/{project_id}/tracks/{animal_id}/frames")
def track_frames(project_id: int, animal_id: int,
                 user: dict = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    rows = (db.query(ImageModel.id, ImageModel.frame_index,
                     ImageModel.filename, ImageModel.timestamp_sec,
                     ImageModel.video_id, Annotation.behavior,
                     Annotation.x, Annotation.y,
                     Annotation.w, Annotation.h)
              .join(Annotation, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False),
                      Annotation.animal_id == int(animal_id))
              .order_by(ImageModel.video_id, ImageModel.frame_index).all())
    items = [{"image_id": int(r.id),
              "frame_index": int(r.frame_index) if r.frame_index is not None else None,
              "video_id": r.video_id, "filename": r.filename,
              "timestamp_sec": r.timestamp_sec, "behavior": r.behavior,
              "bbox": {"x": r.x, "y": r.y, "w": r.w, "h": r.h}} for r in rows]
    return {"items": items, "total": len(items), "animal_id": int(animal_id)}


@router.get("/api/projects/{project_id}/tracks/export")
def export_tracks(project_id: int, format: str = "json",
                  video_id: Optional[int] = None,
                  user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    check_project_access(db, project_id, user)
    fmt = (format or "json").lower()
    if fmt not in ("json", "csv"):
        raise HTTPException(400, "format должен быть json или csv")
    q = (db.query(ImageModel, Annotation)
           .join(Annotation, Annotation.image_id == ImageModel.id)
           .filter(ImageModel.project_id == project_id,
                   ImageModel.is_deleted.is_(False),
                   Annotation.animal_id.isnot(None)))
    if video_id is not None:
        q = q.filter(ImageModel.video_id == video_id)
    rows = q.order_by(Annotation.animal_id, ImageModel.video_id,
                      ImageModel.frame_index).all()
    tracks = defaultdict(list)
    for im, ann in rows:
        aid = int(ann.animal_id)
        cx = ann.x + ann.w / 2
        cy = ann.y + ann.h / 2
        tracks[aid].append({"video_id": im.video_id,
                            "frame_index": int(im.frame_index) if im.frame_index is not None else None,
                            "image_id": int(im.id),
                            "timestamp_sec": im.timestamp_sec,
                            "filename": im.filename,
                            "bbox": {"x": ann.x, "y": ann.y, "w": ann.w, "h": ann.h},
                            "center": [round(cx, 5), round(cy, 5)],
                            "behavior": ann.behavior})
    proj = db.query(Project).filter(Project.id == project_id).first()
    proj_name = proj.name if proj else "project"
    if fmt == "json":
        payload = {"project_id": project_id, "project_name": proj_name,
                   "exported_at": utcnow().isoformat(),
                   "tracks_count": len(tracks),
                   "tracks": [{"animal_id": aid, "frames_count": len(frames),
                               "frames": frames}
                              for aid, frames in sorted(tracks.items())]}
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(content=body, media_type="application/json; charset=utf-8",
                        headers={"Content-Disposition":
                                 "attachment; filename=tracks_project_%d.json" % project_id})
    from io import StringIO
    buf = StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["animal_id", "video_id", "frame_index", "image_id",
                "timestamp_sec", "filename", "x", "y", "w", "h",
                "cx", "cy", "behavior"])
    for aid in sorted(tracks.keys()):
        for fr in tracks[aid]:
            ts = "" if fr["timestamp_sec"] is None else "%.3f" % fr["timestamp_sec"]
            w.writerow([aid, fr["video_id"] or "",
                        fr["frame_index"] if fr["frame_index"] is not None else "",
                        fr["image_id"], ts, fr["filename"],
                        "%.6f" % fr["bbox"]["x"], "%.6f" % fr["bbox"]["y"],
                        "%.6f" % fr["bbox"]["w"], "%.6f" % fr["bbox"]["h"],
                        "%.5f" % fr["center"][0], "%.5f" % fr["center"][1],
                        fr["behavior"] or ""])
    body = buf.getvalue().encode("utf-8-sig")
    return Response(content=body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             "attachment; filename=tracks_project_%d.csv" % project_id})


@router.get("/api/images/{image_id}/motion_vectors")
def motion_vectors_all(image_id: int,
                       user: dict = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    check_image_access(db, image_id, user)
    img = db.query(ImageModel).filter(ImageModel.id == image_id).first()
    if not img:
        raise HTTPException(404, {"key": "error.imageNotFound",
                                 "fallback": "Image not found"})
    if img.video_id is None or img.frame_index is None:
        return {"items": {}, "summary": {"total_with_aid": 0,
                                        "found": 0, "missing": 0},
                "reason": "no_video"}
    out = _check_motion_batch(db, image_id)
    found = sum(1 for v in out.values() if v.get("found"))
    missing = sum(1 for v in out.values() if not v.get("found"))
    return {"items": out,
            "summary": {"total_with_aid": found + missing,
                        "found": found, "missing": missing}}
