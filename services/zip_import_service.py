"""services/zip_import_service.py — [PATCH:STAGE6-PART2-4.6]"""
import os, json, uuid, shutil, zipfile, tempfile, time, re
from collections import defaultdict
import xml.etree.ElementTree as ET
from typing import Optional
from fastapi import HTTPException
from models import Project, ImageModel, Annotation, Keypoint
from services.file_service import _split_name_ext, _detect_image_format, _open_image_safe, letterbox, sanitize_display_name, _is_simple_filename, _unique_name_mem
from services.image_service import _remove_file_safe, _queue_thumb, phash_hex, _invalidate_phash_index, _hex_to_int, _hamming_int
from logger import log_status, utcnow
from config import IMAGE_EXTS, IMPORT_DIR, UPLOAD_DIR, FIXED_SIZE, LETTERBOX_FILL, DEFAULT_OBJECT_CLASS, KEYPOINT_VALID, PHASH_DUPLICATE_THRESHOLD, BATCH_IMPORT_CHUNK
import logging
log = logging.getLogger("db")

# Self-sufficiency: `_process_dataset_zip` was moved
# here from app.py (Stage 6-7), but its helpers were not. Restoring them
# verbatim from pre-refactor app.py so behaviour is unchanged.

IMPORT_PROGRESS: dict = {}


def _resolve_limits() -> dict:
    """[PATCH:RECOMMENDATIONS-LIMITS-FROM-CONFIG] Read MAX_* limits from
    config module at call time.

    Tests patch `config.MAX_*` via monkeypatch; accessing `_cfg.X` inside
    the function (not at module level) ensures patched values are picked up
    on each call (unlike module-level `from config import X`, which binds
    the value at import time).
    """
    import config as _cfg
    return {
        "MAX_UPLOAD_BYTES":          _cfg.MAX_UPLOAD_BYTES,
        "MAX_EXTRACTED_FILES":       _cfg.MAX_EXTRACTED_FILES,
        "MAX_EXTRACTED_BYTES":       _cfg.MAX_EXTRACTED_BYTES,
        "MAX_EXTRACTED_MB":          _cfg.MAX_EXTRACTED_MB,
        "MAX_IMPORT_BYTES":          _cfg.MAX_IMPORT_BYTES,
        "PHASH_DUPLICATE_THRESHOLD": _cfg.PHASH_DUPLICATE_THRESHOLD,
    }


def _update_import_progress(pid, stage, done=0, total=0, msg="", error=None):
    IMPORT_PROGRESS[pid] = {
        "stage": stage, "done": done, "total": total, "msg": msg,
        "error": error, "updated_at": time.time(),
    }


def _collect_image_files(root_dir: str):
    out = []
    for root, dirs, files in os.walk(root_dir):
        for f in files:
            if _is_image_ext(f):
                out.append(os.path.join(root, f))
    return out


def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: str):
    _lim = _resolve_limits()
    _max_files = _lim["MAX_EXTRACTED_FILES"]
    _max_bytes = _lim["MAX_EXTRACTED_BYTES"]
    _max_mb    = _lim["MAX_EXTRACTED_MB"]
    target_root = os.path.realpath(target_dir)
    total_extracted = 0
    file_count = 0
    for member in zf.infolist():
        name = member.filename
        if not name or name in ('.', '..'):
            continue
        if name.startswith('/') or name.startswith('\\'):
            raise HTTPException(400, {"key": "error.zipAbsolutePath", "fallback": f"Абсолютный путь в архиве: {name}", "params": {"name": name}})
        if re.match(r'^[A-Za-z]:', name):
            raise HTTPException(400, {"key": "error.zipWindowsPath", "fallback": f"Windows-абсолютный путь в архиве: {name}", "params": {"name": name}})
        if '\x00' in name:
            raise HTTPException(400, {"key": "error.zipNulByte", "fallback": "NUL в имени файла"})
        target = os.path.realpath(os.path.join(target_dir, name))
        if not (target == target_root or target.startswith(target_root + os.sep)):
            raise HTTPException(400, {"key": "error.zipDangerousPath", "fallback": f"Опасный путь в архиве: {name}", "params": {"name": name}})
        mode = (member.external_attr >> 16) & 0xFFFF
        if mode and (mode & 0xF000) in (0xA000, 0x6000, 0x2000):
            log.warning("skip non-regular file in zip: %s", name)
            continue
        # Директории не считаем как файлы/байты. is_dir() даёт True только
        # для имён с завершающим "/", но некоторые архивы пишут директорию
        # без него. Дополнительно проверяем name-суффикс и S_IFDIR
        # в external_attr (0o170000 — маска типа, 0o040000 — directory).
        if (member.is_dir()
                or name.endswith("/")
                or name.endswith("\\")
                or ((member.external_attr >> 16) & 0o170000) == 0o040000):
            os.makedirs(target, exist_ok=True)
            continue
        file_count += 1
        if file_count > _max_files:
            raise HTTPException(413, {"key": "error.zipTooManyFiles", "fallback": f"Архив содержит более {_max_files} файлов", "params": {"max_files": _max_files}})
        total_extracted += member.file_size
        if total_extracted > _max_bytes:
            raise HTTPException(413, {"key": "error.zipTooLarge", "fallback": f"Распакованный архив превышает {_max_mb} МБ", "params": {"max_mb": _max_mb}})
        if member.compress_size > 0 and member.file_size > 1024 * 1024:
            ratio = member.file_size / member.compress_size
            if ratio > 1000:
                raise HTTPException(400, f"Подозрительная компрессия (ratio={ratio:.0f}): {name}")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)


def _chunks(seq, n=500):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]

def _is_image_ext(name: str) -> bool:
    _, ext = _split_name_ext(name)
    return ext.lower() in IMAGE_EXTS

def _basename_no_ext(name: str) -> str:
    base = os.path.basename(name or "")
    stem, _ = _split_name_ext(base)
    return stem.lower()

def _px_xywh_to_norm(x, y, w, h, iw, ih):
    if iw <= 0 or ih <= 0: return None
    return {"x": x / iw, "y": y / ih, "w": w / iw, "h": h / ih}

def _append_annotation(out: dict, key: str, x: float, y: float, w: float, h: float,
                       label: str = DEFAULT_OBJECT_CLASS, confidence: Optional[float] = None):
    if not key: return
    out[key].append({"x": max(0.0, min(1.0, float(x))), "y": max(0.0, min(1.0, float(y))),
                     "w": max(0.0, min(1.0, float(w))), "h": max(0.0, min(1.0, float(h))),
                     "label": label, "confidence": confidence})














def parse_coco(json_path: str, default_label: str = DEFAULT_OBJECT_CLASS):
    with open(json_path, "r", encoding="utf-8") as _f:
        data = json.load(_f)
    imgs = {i["id"]: i for i in data.get("images", [])}
    out = defaultdict(list)
    for ann in data.get("annotations", []):
        img = imgs.get(ann.get("image_id"))
        if not img:
            continue
        bbox = ann.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x, y, w, h = bbox
        norm = _px_xywh_to_norm(x, y, w, h, img.get("width", 0), img.get("height", 0))
        if not norm:
            continue
        _append_annotation(out, _basename_no_ext(img.get("file_name", "")),
                           norm["x"], norm["y"], norm["w"], norm["h"],
                           default_label, ann.get("score"))
    return out
# moved parse_yolo

def parse_yolo(zip_dir: str, default_label: str = DEFAULT_OBJECT_CLASS):
    out = defaultdict(list)
    labels_dirs = []
    for root, dirs, files in os.walk(zip_dir):
        if os.path.basename(root) == "labels":
            labels_dirs.append(root)
            continue
        has_txt = any(f.lower().endswith(".txt") for f in files)
        has_img = any(_is_image_ext(f) for f in files)
        if has_txt and has_img:
            labels_dirs.append(root)
    if not labels_dirs:
        return out
    seen = set()
    processed = 0
    for labels_dir in labels_dirs:
        for fn in os.listdir(labels_dir):
            if not fn.lower().endswith(".txt"):
                continue
            stem = _basename_no_ext(fn)
            if stem in seen:
                continue
            seen.add(stem)
            processed += 1
            path = os.path.join(labels_dir, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) < 5:
                            continue
                        try:
                            _cls = int(parts[0])
                            xc, yc, w, h = map(float, parts[1:5])
                        except ValueError:
                            continue
                        _append_annotation(out, stem,
                                           xc - w / 2, yc - h / 2, w, h,
                                           default_label, None)
            except OSError:
                log.exception("parse_yolo: cannot read %s", path)
    log.info("parse_yolo: найдено %d label-директорий, обработано %d .txt",
             len(labels_dirs), processed)
    return out
# moved parse_cvat

def parse_cvat(xml_path: str, default_label: str = DEFAULT_OBJECT_CLASS):
    out = defaultdict(list)
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError:
        return out
    for img in root.findall("image"):
        iw = float(img.get("width") or 0)
        ih = float(img.get("height") or 0)
        key = _basename_no_ext(img.get("name", ""))
        if not key or iw <= 0 or ih <= 0:
            continue
        for box in img.findall("box"):
            try:
                xtl = float(str(box.get("xtl") or 0))
                ytl = float(str(box.get("ytl") or 0))
                xbr = float(str(box.get("xbr") or 0))
                ybr = float(str(box.get("ybr") or 0))
            except (TypeError, ValueError):
                continue
            x, y = xtl, ytl
            w, h = xbr - xtl, ybr - ytl
            if w <= 0 or h <= 0:
                continue
            norm = _px_xywh_to_norm(x, y, w, h, iw, ih)
            if not norm:
                continue
            _append_annotation(out, key, norm["x"], norm["y"], norm["w"], norm["h"],
                               default_label)
    return out

_UNSUPPORTED_LS_TYPES = set()
# moved parse_label_studio

def parse_label_studio(json_path: str, default_label: str = DEFAULT_OBJECT_CLASS):
    out = defaultdict(list)
    try:
        with open(json_path, "r", encoding="utf-8") as _f:
            data = json.load(_f)
    except (OSError, json.JSONDecodeError):
        return out
    if not isinstance(data, list):
        data = [data]
    for item in data:
        img_path = ((item.get("data") or {}).get("image") or "")
        key = _basename_no_ext(img_path)
        if not key:
            continue
        for ann_block in item.get("annotations", []) or []:
            for r in ann_block.get("result", []) or []:
                if r.get("type") != "rectanglelabels":
                    t = r.get("type", "unknown")
                    if t not in _UNSUPPORTED_LS_TYPES:
                        _UNSUPPORTED_LS_TYPES.add(t)
                        log.info("parse_label_studio: пропускаю тип %r", t)
                    continue
                val = r.get("value", {})
                _append_annotation(out, key,
                                   val.get("x", 0) / 100,
                                   val.get("y", 0) / 100,
                                   val.get("width", 0) / 100,
                                   val.get("height", 0) / 100,
                                   default_label)
    return out
# moved detect_format

def detect_format(zip_dir: str):
    files = []
    for root, dirs, fs in os.walk(zip_dir):
        for f in fs:
            files.append(os.path.join(root, f))
    for p in files:
        if p.lower().endswith(".json"):
            try:
                with open(p, "r", encoding="utf-8") as _f:
                    data = json.load(_f)
                if isinstance(data, dict) and "annotations" in data and "images" in data:
                    return ("coco", p)
            except Exception:
                pass
    for p in files:
        if p.lower().endswith(".xml"):
            try:
                with open(p, "rb") as _f:
                    head = _f.read(1024)
                if b"<annotations" in head or b"<image" in head:
                    return ("cvat", p)
            except Exception:
                pass
    for p in files:
        if p.lower().endswith(".json"):
            try:
                with open(p, "r", encoding="utf-8") as _f:
                    data = json.load(_f)
                if isinstance(data, list) and data and isinstance(data[0], dict) and "annotations" in data[0]:
                    return ("ls", p)
                if isinstance(data, dict) and "annotations" in data:
                    return ("ls", p)
            except Exception:
                pass
    for root, dirs, fs in os.walk(zip_dir):
        if os.path.basename(root) == "labels":
            return ("yolo", root)
    return (None, None)

def _process_dataset_zip(zip_path: str, project_id: int, db, cancel_event=None, source: str = "upload") -> dict:
    # resolve test-monkeypatchable limits
    _lim = _resolve_limits()
    _max_upload_bytes = _lim["MAX_UPLOAD_BYTES"]
    proj = db.query(Project).filter(Project.id == project_id,
                                     Project.is_deleted.is_(False)).first()
    if not proj:
        raise HTTPException(404, {"key": "error.projectNotFound", "fallback": "Project not found"})
    project_class = proj.object_class or DEFAULT_OBJECT_CLASS

    tmp_dir = tempfile.mkdtemp(prefix="pdb_import_", dir=IMPORT_DIR)
    try:
        try:
            with zipfile.ZipFile(zip_path) as z:
                _safe_extract_zip(z, tmp_dir)
        except zipfile.BadZipFile:
            raise HTTPException(400, {"key": "error.invalidZip", "fallback": "Файл не является zip-архивом"})

        fmt, src = detect_format(tmp_dir)
        image_files_peek = _collect_image_files(tmp_dir)
        if not fmt and not image_files_peek:
            raise HTTPException(400, {"key": "error.emptyArchive", "fallback": "Архив пуст или не содержит данных"})
        if not fmt:
            fmt = "images_only"

        existing = (db.query(ImageModel)
                      .filter(ImageModel.project_id == project_id,
                              ImageModel.is_deleted.is_(False)).all())
        by_stem = {}
        for im in existing:
            stem, _ = _split_name_ext(im.filename)
            by_stem[stem.lower()] = im
        used_names = {fn for (fn,) in db.query(ImageModel.filename)
                                        .filter(ImageModel.project_id == project_id,
                                                ImageModel.is_deleted.is_(False))
                                        .all()}
        def _lsh_chunks(h_int):
            return [
                h_int & 0x3FF,
                (h_int >> 10) & 0x3FF,
                (h_int >> 20) & 0x3FF,
                (h_int >> 30) & 0x3FF,
                (h_int >> 40) & 0x3FF,
                (h_int >> 50) & 0x3FF,
                (h_int >> 60) & 0xF,
            ]

        _lsh_index = [dict() for _ in range(7)]
        _lsh_all = []
        for r in db.query(ImageModel.id, ImageModel.filename, ImageModel.phash).filter(
                ImageModel.project_id == project_id,
                ImageModel.is_deleted.is_(False),
                ImageModel.phash.isnot(None)).all():
            if r.phash and len(r.phash) >= 4:
                _h = _hex_to_int(r.phash)
                if _h < 0:
                    continue
                _entry = (r.id, r.filename, r.phash, _h)
                _lsh_all.append(_entry)
                for _i, _c in enumerate(_lsh_chunks(_h)):
                    _lsh_index[_i].setdefault(_c, []).append(_entry)

        def _find_dup_mem(ph):
            if not ph or len(ph) < 4:
                return None
            target_int = _hex_to_int(ph)
            if target_int < 0:
                return None
            _cands = set()
            for _i, _c in enumerate(_lsh_chunks(target_int)):
                for _entry in _lsh_index[_i].get(_c, ()):
                    _cands.add(id(_entry))
            for _entry in _lsh_all:
                if id(_entry) not in _cands:
                    continue
                if _hamming_int(target_int, _entry[3]) <= PHASH_DUPLICATE_THRESHOLD:
                    return (_entry[0], _entry[1], _entry[2])
            return None

        imported_images = 0
        skipped_duplicates = 0
        failed_images = 0
        pending = []

        def _flush_pending():
            nonlocal pending
            if not pending:
                return
            db.flush()
            for (im_x, path_x, stem_x) in pending:
                _queue_thumb(im_x.id, path_x)
                try:
                    from services.auto_blur_service import schedule_auto_blur
                    schedule_auto_blur(im_x.id, project_id)
                except Exception:
                    pass
                by_stem[stem_x] = im_x
            pending = []

        total_files = len(image_files_peek)
        for img_idx, img_path in enumerate(image_files_peek):
            if img_idx % 10 == 0:
                _update_import_progress(project_id, "process", img_idx, total_files, "Обработка изображений")

            # V10.4.1: проверка отмены до обработки каждого файла.
            if cancel_event and cancel_event.is_set():
                db.rollback()
                raise HTTPException(409, {"key": "error.importCancelled", "fallback": "Импорт отменён"})
            original_name = os.path.basename(img_path)
            # Проверяем имя до использования:
            # '..' как подстрока, NUL-байты, control-chars. Zip-slip уже
            # защищён, но имя с '..' проходило бы дальше как display_name.
            if not _is_simple_filename(original_name):
                failed_images += 1
                continue
            stem_l = _basename_no_ext(original_name)
            if stem_l in by_stem:
                # Уникализируем стем,
                # чтобы не терять файлы a.jpg / a.png с одинаковым стемом.
                _coll_n = 2
                _stem_new = f"{stem_l}__{_coll_n}"
                while _stem_new in by_stem:
                    _coll_n += 1
                    _stem_new = f"{stem_l}__{_coll_n}"
                log.warning("import: коллизия стема %r -> %r", stem_l, _stem_new)
                stem_l = _stem_new
            # одна картинка 500MB
            # съест память при Image.open → OOM. Проверяем размер до чтения.
            try:
                if os.path.getsize(img_path) > _max_upload_bytes:
                    failed_images += 1
                    continue
            except OSError:
                failed_images += 1
                continue
            try:
                with open(img_path, "rb") as f:
                    head = f.read(16)
                if not _detect_image_format(head):
                    failed_images += 1
                    continue
            except OSError:
                failed_images += 1
                continue
            # _open_image_safe
            # защищает от decompression bomb (DecompressionBombError
            # → HTTPException(413)), единообразно с загрузкой.
            try:
                with open(img_path, "rb") as _zf:
                    _zdata = _zf.read()
                pil = _open_image_safe(_zdata).convert("RGB")
            except HTTPException:
                failed_images += 1
                continue
            except Exception:
                failed_images += 1
                continue
            _orig_w, _orig_h = pil.size
            pil = letterbox(pil, FIXED_SIZE, LETTERBOX_FILL)
            new_fname = f"{uuid.uuid4().hex}.jpg"
            new_path = os.path.join(UPLOAD_DIR, new_fname)
            try:
                pil.save(new_path, "JPEG", quality=95)
            except Exception:
                failed_images += 1
                continue
            try:
                ph = phash_hex(new_path)
            except Exception:
                ph = ""
            if ph:
                dup = _find_dup_mem(ph)
                if dup:
                    _remove_file_safe(new_path)
                    skipped_duplicates += 1
                    continue
            display_name = sanitize_display_name(original_name, fallback=new_fname)
            unique_name = _unique_name_mem(display_name, used_names)
            try:
                fsize = os.path.getsize(new_path)
            except OSError:
                fsize = 0
            im = ImageModel(
                project_id=project_id, filename=unique_name, path=new_path,
                width=FIXED_SIZE[0], height=FIXED_SIZE[1],
                original_width=_orig_w, original_height=_orig_h,
                is_deleted=False, phash=ph or None, is_hard=False,
                created_at=utcnow(), file_size=fsize,
            )
            db.add(im)
            if ph and len(ph) >= 4:
                _h_new = _hex_to_int(ph)
                if _h_new >= 0:
                    _entry_new = (None, unique_name, ph, _h_new)
                    _lsh_all.append(_entry_new)
                    for _i, _c in enumerate(_lsh_chunks(_h_new)):
                        _lsh_index[_i].setdefault(_c, []).append(_entry_new)
            pending.append((im, new_path, stem_l))
            imported_images += 1
            if len(pending) >= BATCH_IMPORT_CHUNK:
                _flush_pending()
        _flush_pending()
        db.commit()
        _invalidate_phash_index(project_id)

        parsed = {}
        if fmt == "coco":
            parsed = parse_coco(src, default_label=project_class)
        elif fmt == "yolo":
            parsed = parse_yolo(tmp_dir, default_label=project_class)
        elif fmt == "cvat":
            from services.cvat_service import parse_cvat_xml
            parsed = parse_cvat_xml(src)
        elif fmt == "ls":
            parsed = parse_label_studio(src, default_label=project_class)

        matched = 0
        added_anns = 0
        unmatched = []
        image_ids_to_clear = []
        anns_to_add = []
        for stem, boxes in parsed.items():
            im = by_stem.get(stem)
            if not im:
                unmatched.append(stem)
                continue
            image_ids_to_clear.append(im.id)
            for b in boxes:
                new_ann = Annotation(
                    image_id=im.id,
                    x=max(0.0, min(1.0, b["x"])),
                    y=max(0.0, min(1.0, b["y"])),
                    w=max(0.0, min(1.0, b["w"])),
                    h=max(0.0, min(1.0, b["h"])),
                    label=b.get("label", project_class),
                    confidence=b.get("confidence"),
                    is_frozen=False,
                    animal_id=b.get("animal_id"),
                    behavior=b.get("behavior"),
                )
                db.add(new_ann)
                anns_to_add.append((new_ann, b.get("keypoints", [])))
                added_anns += 1
            matched += 1

        if image_ids_to_clear:
            _clear_ann_ids = [row.id for row in db.query(Annotation.id).filter(
                Annotation.image_id.in_(image_ids_to_clear)).all()]
            if _clear_ann_ids:
                db.query(Keypoint).filter(Keypoint.annotation_id.in_(_clear_ann_ids)).delete(synchronize_session=False)
            db.query(Annotation).filter(
                Annotation.image_id.in_(image_ids_to_clear)
            ).delete(synchronize_session=False)

        if anns_to_add:
            db.flush()
            for new_ann, kps in anns_to_add:
                for kp in kps:
                    nm = str(kp.get("name", "")).strip()
                    if nm in KEYPOINT_VALID:
                        db.add(Keypoint(
                            annotation_id=new_ann.id,
                            name=nm,
                            x=max(0.0, min(1.0, float(kp.get("x", 0)))),
                            y=max(0.0, min(1.0, float(kp.get("y", 0)))),
                            visibility=max(0.0, min(1.0, float(kp.get("visibility", 1.0))))
                        ))
        db.commit()

        try:
            from services.metrics import (
                imports_completed_total as _imp_metric,
                images_uploaded_total as _up_metric,
            )
            _imp_metric.labels(source=(source or "unknown")).inc()
            _up_metric.inc(int(imported_images or 0))
        except Exception:
            pass
        log_status("success", "import",
                   f"Импорт проекта #{project_id}: формат {fmt}, класс «{project_class}», "
                   f"+{imported_images} фото, дубл. {skipped_duplicates}, "
                   f"рамок {added_anns}, не найдено {len(unmatched)}")
        return {"status": "ok", "format": fmt,
                "imported_images": imported_images,
                "skipped_duplicates": skipped_duplicates,
                "failed_images": failed_images,
                "matched_images": matched,
                "added_annotations": added_anns,
                "unmatched": unmatched[:50],
                "unmatched_count": len(unmatched)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


IMPORT_PROGRESS = {}
