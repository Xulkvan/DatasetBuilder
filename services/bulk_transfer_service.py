"""services/bulk_transfer_service.py — [PATCH:STAGE6-PART2-4.4]"""
import os, uuid, logging, shutil
from fastapi import HTTPException
from collections import defaultdict
from models import Project, ImageModel, Annotation, Keypoint, Tag, ImageTag
from services.image_service import _remove_file_safe, _queue_thumb
from services.file_service import _unique_name_mem
from logger import utcnow, log_status
from config import UPLOAD_DIR, DEFAULT_OBJECT_CLASS
from schemas import BulkMoveCopyIn

log = logging.getLogger("db")

# marker: indicates atomic bulk_transfer patch (STAGE7) has been applied.
# Used only for idempotency — no side effects.
_atomic_bulk_marker = True

def _chunks(seq, n=500):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]




def _bulk_transfer(db, payload: BulkMoveCopyIn, copy: bool):
    ids = payload.image_ids or []
    if not ids:
        raise HTTPException(400, "Пустой список")
    if len(ids) > 2000:
        raise HTTPException(400, "Максимум 2000 за раз")
    dst_proj = db.query(Project).filter(Project.id == payload.target_project_id,
                                         Project.is_deleted.is_(False)).first()
    if not dst_proj:
        raise HTTPException(404, "Целевой проект не найден")
    imgs = db.query(ImageModel).filter(ImageModel.id.in_(ids),
                                        ImageModel.is_deleted.is_(False)).all()
    if not imgs:
        raise HTTPException(404, "Изображения не найдены")
    if any(im.project_id == dst_proj.id for im in imgs):
        raise HTTPException(400, "Некоторые изображения уже в этом проекте")
    dst_class = dst_proj.object_class or DEFAULT_OBJECT_CLASS
    # source project_ids ДО мутации
    _src_project_ids = {im.project_id for im in imgs if im.project_id != dst_proj.id}
    used_names = {fn for (fn,) in db.query(ImageModel.filename)
                    .filter(ImageModel.project_id == dst_proj.id,
                            ImageModel.is_deleted.is_(False)).all()}
    # precompute для устранения N+1
    _bulk_im_ids = [im.id for im in imgs]
    _anns_by_img_bulk = defaultdict(list)
    for _c in _chunks(_bulk_im_ids, 500):
        for _a in db.query(Annotation).filter(Annotation.image_id.in_(_c)).all():
            _anns_by_img_bulk[_a.image_id].append(_a)
    _bulk_ann_ids = [a.id for lst in _anns_by_img_bulk.values() for a in lst]
    _kp_by_ann_bulk = defaultdict(list)
    for _c in _chunks(_bulk_ann_ids, 500):
        for _kp in db.query(Keypoint).filter(Keypoint.annotation_id.in_(_c)).all():
            _kp_by_ann_bulk[_kp.annotation_id].append(_kp)
    _tags_by_img_bulk = defaultdict(list)
    for _c in _chunks(_bulk_im_ids, 500):
        for _it in db.query(ImageTag).filter(ImageTag.image_id.in_(_c)).all():
            _tags_by_img_bulk[_it.image_id].append(_it.tag_id)
    moved = 0
    # atomic bulk_transfer: при ошибке — rollback БД
    # и удаление уже скопированных файлов (см. except ниже).
    _created_paths: list[str] = []
    try:
        for im in imgs:
            src_path = im.path
            new_path = src_path
            if copy:
                new_fname = f"{uuid.uuid4().hex}.jpg"
                new_path = os.path.join(UPLOAD_DIR, new_fname)
                try:
                    shutil.copyfile(src_path, new_path)
                except OSError:
                    continue
                _created_paths.append(new_path)
            final_name = _unique_name_mem(im.filename, used_names)
            if copy:
                try:
                    new_im = ImageModel(
                        project_id=dst_proj.id, filename=final_name, path=new_path,
                        width=im.width, height=im.height,
                        original_width=im.original_width, original_height=im.original_height,
                        is_deleted=False, phash=im.phash, is_hard=im.is_hard,
                        video_id=None, frame_index=None,
                        timestamp_sec=im.timestamp_sec,
                        is_stream_frame=im.is_stream_frame,
                        created_at=im.created_at or utcnow(), file_size=im.file_size,
                    )
                    db.add(new_im)
                    db.flush()
                    # данные из batch-кэша
                    anns = _anns_by_img_bulk.get(im.id, [])
                    _kp_map = _kp_by_ann_bulk
                    for a in anns:
                        _new_ann = Annotation(image_id=new_im.id,
                                              x=a.x, y=a.y, w=a.w, h=a.h,
                                              label=dst_class, confidence=a.confidence,
                                              is_frozen=a.is_frozen,
                                              behavior=a.behavior,
                                              animal_id=a.animal_id)
                        db.add(_new_ann)
                        db.flush()
                        for _kp in _kp_map.get(a.id, []):
                            db.add(Keypoint(annotation_id=_new_ann.id,
                                            name=_kp.name, x=_kp.x, y=_kp.y,
                                            visibility=_kp.visibility))
                    src_tag_ids = _tags_by_img_bulk.get(im.id, [])
                    if src_tag_ids:
                        src_tags = {t.id: t.name for t in db.query(Tag).filter(Tag.id.in_(src_tag_ids)).all()}
                        dst_tags = {t.name: t.id for t in db.query(Tag).filter(Tag.project_id == dst_proj.id).all()}
                        for tid in src_tag_ids:
                            tname = src_tags.get(tid)
                            dst_tid = dst_tags.get(tname) if tname else None
                            if dst_tid:
                                db.add(ImageTag(image_id=new_im.id, tag_id=dst_tid))
                    _queue_thumb(new_im.id, new_im.path)
                except Exception as e:
                    db.rollback()
                    if os.path.exists(new_path):
                        _remove_file_safe(new_path)
                    log.error("Ошибка при копировании БД для %s: %s", im.filename, e)
                    continue
            else:
                im.project_id = dst_proj.id
                im.filename = final_name
                im.video_id = None
                im.frame_index = None
                db.query(Annotation).filter(Annotation.image_id == im.id).update(
                    {"label": dst_class}, synchronize_session=False
                )
            moved += 1
        db.commit()
    except Exception:
        db.rollback()
        for _p in _created_paths:
            try:
                if os.path.exists(_p):
                    os.remove(_p)
            except OSError:
                pass
        raise
    # инвалидация pHash/stats
    try:
        from services.image_service import (
            _invalidate_phash_index, _invalidate_stats_cache,
        )
        for _pid in (_src_project_ids | {dst_proj.id}):
            _invalidate_phash_index(_pid)
            _invalidate_stats_cache(_pid)
    except Exception:
        pass
    action = "Скопировано" if copy else "Перемещено"
    log_status("info", "project",
               f"{action}: {moved} изображений → проект «{dst_proj.name}»")
    return {"status": "ok", "moved": moved, "action": "copy" if copy else "move"}

# moved bulk_move
# moved bulk_copy