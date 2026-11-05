"""[PATCH:STAGE2-C2] CSV-эндпоинты: stats.csv, files.csv, boxes.csv.

Все три — с Content-Disposition: attachment и utf-8-sig (BOM для Excel).
Поддерживают фильтры ?filter=&search=&tag_ids= — совместимы с /stats и
downloadStatsCsv из main.js.
"""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func  # [FIX:STAGE2-mypy-lowconf-imp]
from sqlalchemy.orm import Session

from database import get_db
from models import Project, ImageModel, Annotation, ImageTag
from services.auth_service import get_current_user
from services.project_access import check_project_access


router = APIRouter()


def _get_project(db: Session, project_id: int, user: dict) -> Project:
    check_project_access(db, project_id, user)
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound",
                                  "fallback": "Project not found"})
    return proj


def _parse_tags(tag_ids: str) -> list[int]:
    out: list[int] = []
    if tag_ids:
        for t in tag_ids.split(","):
            try:
                out.append(int(t.strip()))
            except (ValueError, TypeError):
                continue
    return out


def _build_image_query(db: Session, project_id: int,
                       parsed_tags: list[int], search: str):
    q = db.query(ImageModel).filter(
        ImageModel.project_id == project_id,
        ImageModel.is_deleted.is_(False),
    )
    if search:
        q = q.filter(ImageModel.filename.ilike(f"%{search}%"))
    if parsed_tags:
        subq = (db.query(ImageTag.image_id)
                  .filter(ImageTag.tag_id.in_(parsed_tags)).subquery())
        q = q.filter(ImageModel.id.in_(db.query(subq.c.image_id)))
    return q


def _csv_response(text: str, filename: str) -> Response:
    body = text.encode("utf-8-sig")
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/projects/{project_id}/stats.csv")
def export_stats_csv(project_id: int,
                     filter: str = "none",
                     search: str = "",
                     tag_ids: str = "",
                     user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _get_project(db, project_id, user)
    parsed_tags = _parse_tags(tag_ids)
    q = _build_image_query(db, project_id, parsed_tags, search)
    rows = q.order_by(ImageModel.id).all()
    img_ids = [r.id for r in rows]

    stats: dict = {}
    if img_ids:
        raw = db.query(
            Annotation.image_id,
            func.count(Annotation.id),
            func.min(Annotation.confidence),
            func.avg(Annotation.confidence),
        ).filter(Annotation.image_id.in_(img_ids)) \
         .group_by(Annotation.image_id).all()
        # [FIX:STAGE2-mypy-lowconf] Отдельный запрос без case():
        # case((cond, 1), else_=0) не типизируется mypy без SQLAlchemy-plugin
        # (Column.__lt__ даёт bool, не ColumnElement[bool]). Простое
        # filter(cond) типизируется корректно.
        low_raw = db.query(
            Annotation.image_id, func.count(Annotation.id),
        ).filter(
            Annotation.image_id.in_(img_ids),
            Annotation.confidence.isnot(None),
            Annotation.confidence < 0.5,
        ).group_by(Annotation.image_id).all()
        low_map = {int(iid): int(c or 0) for iid, c in low_raw}
        for iid, cnt, mn, av in raw:
            stats[iid] = (
                int(cnt or 0),
                None if mn is None else float(mn),
                None if av is None else float(av),
                low_map.get(int(iid), 0),
            )

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["filename", "annotation_count", "min_confidence",
                "avg_confidence", "low_conf_count"])
    for r in rows:
        s = stats.get(r.id, (0, None, None, 0))
        if filter == "unannotated" and s[0] > 0:
            continue
        if filter == "lowconf" and s[3] == 0:
            continue
        mn = "" if s[1] is None else "%.4f" % s[1]
        av = "" if s[2] is None else "%.4f" % s[2]
        w.writerow([r.filename, s[0], mn, av, s[3]])
    return _csv_response(buf.getvalue(), f"stats_project_{project_id}.csv")


@router.get("/api/projects/{project_id}/files.csv")
def export_files_csv(project_id: int,
                     search: str = "",
                     tag_ids: str = "",
                     user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _get_project(db, project_id, user)
    parsed_tags = _parse_tags(tag_ids)
    q = _build_image_query(db, project_id, parsed_tags, search)
    rows = q.order_by(ImageModel.id).all()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["id", "filename", "width", "height", "file_size",
                "created_at", "video_id", "frame_index", "timestamp_sec"])
    for r in rows:
        created = r.created_at.isoformat() if r.created_at else ""
        ts = "" if r.timestamp_sec is None else "%.3f" % r.timestamp_sec
        w.writerow([
            r.id, r.filename, r.width or 0, r.height or 0,
            r.file_size or 0, created,
            r.video_id or "",
            r.frame_index if r.frame_index is not None else "",
            ts,
        ])
    return _csv_response(buf.getvalue(), f"files_project_{project_id}.csv")


@router.get("/api/projects/{project_id}/boxes.csv")
def export_boxes_csv(project_id: int,
                     user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _get_project(db, project_id, user)
    rows = (db.query(Annotation, ImageModel)
              .join(ImageModel, Annotation.image_id == ImageModel.id)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False))
              .order_by(ImageModel.id, Annotation.id)
              .all())
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["image_id", "filename", "annotation_id",
                "x", "y", "w", "h", "label", "confidence",
                "behavior", "animal_id"])
    for a, im in rows:
        w.writerow([
            im.id, im.filename, a.id,
            "%.6f" % a.x, "%.6f" % a.y, "%.6f" % a.w, "%.6f" % a.h,
            a.label,
            "" if a.confidence is None else "%.4f" % a.confidence,
            a.behavior or "",
            "" if a.animal_id is None else a.animal_id,
        ])
    return _csv_response(buf.getvalue(), f"boxes_project_{project_id}.csv")
