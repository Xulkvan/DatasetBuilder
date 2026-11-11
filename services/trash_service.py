"""Trash cleaner: purge videos and cleanup expired."""
import os
import time
import threading
import logging
from datetime import timedelta
from database import SessionLocal
from models import ImageModel, Video, Annotation, ImageTag, Project, Tag, Keypoint
from services.image_service import _remove_file_safe, _remove_thumb
from services.settings_service import get_trash_ttl_days
from services.project_service import _purge_projects
from logger import utcnow
from logger import log_status
# logger.py всегда экспортирует log_status —
# try/except с None ломал mypy-типизацию. Прямой импорт.

log = logging.getLogger("db")

def _purge_videos(db, video_ids):
    if not video_ids: return 0
    videos = db.query(Video).filter(Video.id.in_(video_ids)).all()
    video_files = []
    all_img_ids = []
    all_img_paths = []
    for v in videos:
        video_files.append(v.path)
        imgs = db.query(ImageModel.id, ImageModel.path).filter(ImageModel.video_id == v.id).all()
        for iid, ipath in imgs:
            all_img_ids.append(iid)
            all_img_paths.append(ipath)
    if all_img_ids:
        _all_ann_ids = []
        for _i in range(0, len(all_img_ids), 500):
            _c = all_img_ids[_i:_i + 500]
            for row in db.query(Annotation.id).filter(Annotation.image_id.in_(_c)).all():
                _all_ann_ids.append(row.id)
        for _i in range(0, len(_all_ann_ids), 500):
            _c = _all_ann_ids[_i:_i + 500]
            db.query(Keypoint).filter(Keypoint.annotation_id.in_(_c)).delete(synchronize_session=False)
        for _i in range(0, len(all_img_ids), 500):
            _c = all_img_ids[_i:_i + 500]
            db.query(Annotation).filter(Annotation.image_id.in_(_c)).delete(synchronize_session=False)
            db.query(ImageTag).filter(ImageTag.image_id.in_(_c)).delete(synchronize_session=False)
            db.query(ImageModel).filter(ImageModel.id.in_(_c)).delete(synchronize_session=False)
    db.query(Video).filter(Video.id.in_(video_ids)).delete(synchronize_session=False)
    db.commit()
    for p in all_img_paths:
        _remove_file_safe(p)
    for iid in all_img_ids:
        _remove_thumb(iid)
    for vp in video_files:
        _remove_file_safe(vp)
    return len(videos)

def cleanup_expired_data(db) -> int:
    """Удаляет изображения старше project.data_retention_days.

    Для каждого проекта с retention>0:
      * cutoff = now - N дней;
      * chunked-цикл по images где created_at < cutoff и is_deleted=False;
      * сначала удаляем Keypoint/Annotation/ImageTag/BlurRegion/ImageLock,
        затем ImageModel;
      * после commit — удаляем файлы с диска (best-effort).

    Возвращает общее число удалённых изображений.
    """
    from datetime import timedelta as _td
    from models import Project as _P, ImageModel as _IM
    from models import Annotation as _A, Keypoint as _K
    from models import ImageTag as _IT, BlurRegion as _BR
    from models import ImageLock as _IL
    from services.image_service import (
        _remove_file_safe as _rfs, _remove_thumb as _rt,
    )

    now = utcnow()
    projects = (db.query(_P)
                  .filter(_P.is_deleted.is_(False),
                          _P.data_retention_days > 0).all())
    total = 0
    for proj in projects:
        try:
            days = int(proj.data_retention_days or 0)
        except (TypeError, ValueError):
            continue
        if days <= 0:
            continue
        cutoff = now - _td(days=days)
        while True:
            rows = (db.query(_IM.id, _IM.path)
                      .filter(_IM.project_id == proj.id,
                              _IM.is_deleted.is_(False),
                              _IM.created_at.isnot(None),
                              _IM.created_at < cutoff)
                      .limit(500).all())
            if not rows:
                break
            ids = [r.id for r in rows]
            paths = [r.path for r in rows]
            ann_ids = [a.id for a in db.query(_A.id)
                                   .filter(_A.image_id.in_(ids)).all()]
            if ann_ids:
                db.query(_K).filter(_K.annotation_id.in_(ann_ids)) \
                    .delete(synchronize_session=False)
            db.query(_A).filter(_A.image_id.in_(ids)) \
                .delete(synchronize_session=False)
            db.query(_IT).filter(_IT.image_id.in_(ids)) \
                .delete(synchronize_session=False)
            db.query(_BR).filter(_BR.image_id.in_(ids)) \
                .delete(synchronize_session=False)
            db.query(_IL).filter(_IL.image_id.in_(ids)) \
                .delete(synchronize_session=False)
            db.query(_IM).filter(_IM.id.in_(ids)) \
                .delete(synchronize_session=False)
            db.commit()
            for p in paths:
                _rfs(p)
            for iid in ids:
                _rt(iid)
            total += len(ids)
            if len(rows) < 500:
                break
    if total:
        try:
            log_status("info", "trash",
                       f"Retention: удалено {total} изображений "
                       f"(data_retention_days)")
        except Exception:
            pass
    return total


def cleanup_expired_trash(db) -> int:
    from collections import defaultdict
    default_ttl = get_trash_ttl_days(db)
    now = utcnow()
    total = 0
    proj_rows = db.query(Project.id, Project.trash_ttl_days_override).filter(Project.is_deleted.is_(True)).all()
    ttl_by_project = {pid: (int(o) if o is not None else default_ttl) for pid, o in proj_rows}

    proj_by_ttl = defaultdict(list)
    for pid, ttl in ttl_by_project.items():
        if ttl > 0: proj_by_ttl[ttl].append(pid)
    for ttl, pids in proj_by_ttl.items():
        cutoff = now - timedelta(days=ttl)
        while True:
            chunk = db.query(Project.id).filter(Project.id.in_(pids), Project.deleted_at.isnot(None), Project.deleted_at < cutoff).limit(50).all()
            if not chunk: break
            ids = [r.id for r in chunk]
            _purge_projects(db, ids)
            total += len(ids)
            if len(chunk) < 50: break

    vid_rows = db.query(Video.id, Video.project_id, Video.deleted_at).filter(Video.is_deleted.is_(True)).all()
    vid_to_purge = []
    for vid, pid, deleted_at in vid_rows:
        ttl = ttl_by_project.get(pid, default_ttl)
        if ttl <= 0 or not deleted_at: continue
        if deleted_at < now - timedelta(days=ttl): vid_to_purge.append(vid)
    if vid_to_purge:
        total += _purge_videos(db, vid_to_purge)

    CHUNK = 500
    img_rows = db.query(ImageModel.id, ImageModel.project_id).filter(ImageModel.is_deleted.is_(True)).all()
    imgs_by_ttl = defaultdict(list)
    for iid, pid in img_rows:
        ttl = ttl_by_project.get(pid, default_ttl)
        if ttl > 0: imgs_by_ttl[ttl].append(iid)
    for ttl, iids in imgs_by_ttl.items():
        cutoff = now - timedelta(days=ttl)
        _iids_set = set(iids)
        _cursor = 0
        while True:
            if _cursor >= len(iids):
                break
            _chunk_ids = iids[_cursor:_cursor + CHUNK]
            _cursor += CHUNK
            cands = db.query(ImageModel.id, ImageModel.path).filter(
                ImageModel.id.in_(_chunk_ids), ImageModel.deleted_at.isnot(None), ImageModel.deleted_at < cutoff
            ).limit(CHUNK).all()
            if not cands: break
            cids = [r.id for r in cands]
            cpaths = [r.path for r in cands]
            _ann_ids = [row.id for row in db.query(Annotation.id).filter(
                Annotation.image_id.in_(cids)).all()]
            if _ann_ids:
                db.query(Keypoint).filter(Keypoint.annotation_id.in_(_ann_ids)).delete(synchronize_session=False)
            db.query(Annotation).filter(Annotation.image_id.in_(cids)).delete(synchronize_session=False)
            db.query(ImageTag).filter(ImageTag.image_id.in_(cids)).delete(synchronize_session=False)
            db.query(ImageModel).filter(ImageModel.id.in_(cids)).delete(synchronize_session=False)
            db.commit()
            for p in cpaths: _remove_file_safe(p)
            for iid in cids: _remove_thumb(iid)
            total += len(cands)
            if len(cands) < CHUNK: break
    return total

def _start_trash_cleaner_thread():
    def loop():
        while True:
            try:
                db = SessionLocal()
                try:
                    n = cleanup_expired_trash(db)
                    if n: log.info("Корзина: удалено устаревших объектов %d", n)
                finally:
                    db.close()
            except Exception:
                log.exception("trash cleaner error")
            time.sleep(6 * 3600)
    t = threading.Thread(target=loop, daemon=True, name="trash-cleaner")
    t.start()


def start_retention_cleaner_thread():
    """Stage 3.10: retention cleaner (moved from app.py)."""
    def _loop():
        while True:
            try:
                db = SessionLocal()
                try:
                    n = cleanup_expired_data(db)
                    if n:
                        log.info("Retention: удалено %d изображений", n)
                        try:
                            log_status("info", "trash",
                                       f"Retention: удалено {n} изображений "
                                       f"(старше data_retention_days)")
                        except Exception:
                            pass
                finally:
                    db.close()
            except Exception:
                log.exception("retention cleaner error")
            time.sleep(24 * 3600)
    t = threading.Thread(target=_loop, daemon=True, name="retention-cleaner")
    t.start()
    return t
