"""Service for image-related helpers (pHash, IoU, thumbnails, stats, duplicates)."""
import os
import sys
import time
import math
import threading
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Optional

from sqlalchemy import func, case

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from PIL import Image
from models import Project, ImageModel, Annotation

log = logging.getLogger("db")

# === Paths ===
if getattr(sys, 'frozen', False):
    _DEFAULT_DATA_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _DEFAULT_DATA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.getenv("DATA_ROOT", _DEFAULT_DATA_ROOT)
THUMB_DIR = os.path.join(DATA_ROOT, "thumbs")

THUMB_SIZE = (64, 64)
PHASH_DUPLICATE_THRESHOLD = 6
SIMILAR_DEFAULT_THRESHOLD = 12
CONF_THRESHOLD = 0.25


# === File removal ===
def _remove_file_safe(p: str):
    if not p:
        return
    try:
        real = os.path.realpath(p)
        if not real.startswith(os.path.realpath(DATA_ROOT) + os.sep):
            log.debug("skip removal outside data root: %s", p)
            return
        if os.path.isfile(real):
            os.remove(real)
    except OSError as e:
        log.warning("cannot remove %s: %s", p, e)
    except Exception:
        log.exception("unexpected error removing %s", p)


# === pHash (DCT) ===
_DCT_TABLE_CACHE = {}
_NP_DCT_CACHE = {}

def _dct_cos_table(n: int):
    t = _DCT_TABLE_CACHE.get(n)
    if t is None:
        t = [[math.cos((2 * x + 1) * u * math.pi / (2 * n)) for x in range(n)] for u in range(n)]
        _DCT_TABLE_CACHE[n] = t
    return t

def _dct_matrix_np(N: int, hash_size: int):
    key = (N, hash_size)
    if key in _NP_DCT_CACHE:
        return _NP_DCT_CACHE[key]
    C = _np.zeros((hash_size, N), dtype=_np.float32)
    for u in range(hash_size):
        for x in range(N):
            C[u, x] = _np.cos((2 * x + 1) * u * _np.pi / (2 * N))
    _NP_DCT_CACHE[key] = C
    return C

def phash_hex(image_path, hash_size=8, highfreq_factor=4) -> str:
    N = hash_size * highfreq_factor
    try:
        img = Image.open(image_path).convert("L").resize((N, N), Image.Resampling.LANCZOS)
    except Exception:
        return ""
    if _HAS_NUMPY:
        try:
            arr = _np.asarray(img, dtype=_np.float32)
            C = _dct_matrix_np(N, hash_size)
            dct = C @ arr @ C.T
            flat = dct.flatten()
            vals = flat[1:]
            med = _np.median(vals)
            value = 0
            for b in (flat > med):
                value = (value << 1) | int(b)
            return format(value, "016x")
        except Exception:
            log.exception("phash numpy path failed, falling back to python")
    pixels = list(img.getdata())
    cos_t = _dct_cos_table(N)
    row_dct = [[0.0] * N for _ in range(hash_size)]
    for u in range(hash_size):
        cu = cos_t[u]
        for y in range(N):
            s = 0.0
            base = y * N
            for x in range(N):
                s += pixels[base + x] * cu[x]
            row_dct[u][y] = s
    dct = [[0.0] * hash_size for _ in range(hash_size)]
    for u in range(hash_size):
        for v in range(hash_size):
            cv = cos_t[v]
            s = 0.0
            for y in range(N):
                s += row_dct[u][y] * cv[y]
            dct[u][v] = s
    vals = []
    for u in range(hash_size):
        for v in range(hash_size):
            if u == 0 and v == 0:
                continue
            vals.append(dct[u][v])
    vals.sort()
    med = vals[len(vals) // 2]
    bits = 0
    for u in range(hash_size):
        for v in range(hash_size):
            bits = (bits << 1) | (1 if dct[u][v] > med else 0)
    return format(bits, "016x")

def hamming_hex(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 64
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 64

def _hex_to_int(h, expected_len: Optional[int] = 16) -> int:
    if not isinstance(h, str) or not h:
        return -1
    if expected_len is not None and len(h) != expected_len:
        return -1
    try:
        return int(h, 16)
    except (TypeError, ValueError):
        return -1

def _hamming_int(a: int, b: int) -> int:
    if a < 0 or b < 0:
        return 64
    return bin(a ^ b).count("1")


# === Multi-Index Hashing (LSH) ===
_PHASH_INDEX_CACHE = {}
_PHASH_INDEX_LOCK = threading.Lock()

def _invalidate_phash_index(project_id: int):
    with _PHASH_INDEX_LOCK:
        _PHASH_INDEX_CACHE.pop(project_id, None)

def _get_phash_index(db, project_id: int):
    with _PHASH_INDEX_LOCK:
        if project_id in _PHASH_INDEX_CACHE:
            return _PHASH_INDEX_CACHE[project_id]
    rows = db.query(ImageModel.id, ImageModel.phash).filter(
        ImageModel.project_id == project_id,
        ImageModel.is_deleted.is_(False),
        ImageModel.phash.isnot(None),
    ).all()
    index = [dict() for _ in range(7)]
    hashes_map = {}
    for r in rows:
        h_int = _hex_to_int(r.phash)
        if h_int < 0:
            continue
        hashes_map[r.id] = h_int
        chunks = [
            h_int & 0x3FF, (h_int >> 10) & 0x3FF, (h_int >> 20) & 0x3FF,
            (h_int >> 30) & 0x3FF, (h_int >> 40) & 0x3FF, (h_int >> 50) & 0x3FF,
            (h_int >> 60) & 0xF,
        ]
        for i, c in enumerate(chunks):
            index[i].setdefault(c, []).append(r.id)
    result = (index, hashes_map)
    with _PHASH_INDEX_LOCK:
        _PHASH_INDEX_CACHE[project_id] = result
    return result

def _find_duplicates_via_index(hash_int, index, hashes_map, exclude_id=None, max_dist=6):
    if hash_int < 0:
        return []
    chunks = [
        hash_int & 0x3FF, (hash_int >> 10) & 0x3FF, (hash_int >> 20) & 0x3FF,
        (hash_int >> 30) & 0x3FF, (hash_int >> 40) & 0x3FF, (hash_int >> 50) & 0x3FF,
        (hash_int >> 60) & 0xF,
    ]
    candidates = set()
    for i, c in enumerate(chunks):
        if c in index[i]:
            candidates.update(index[i][c])
    results = []
    for cid in candidates:
        if cid == exclude_id:
            continue
        c_int = hashes_map[cid]
        dist = bin(hash_int ^ c_int).count("1")
        if dist <= max_dist:
            results.append((cid, dist))
    return sorted(results, key=lambda x: x[1])

def find_duplicate(db, project_id: int, phash: str):
    if not phash or len(phash) < 4:
        return None
    target_int = _hex_to_int(phash)
    index, hashes_map = _get_phash_index(db, project_id)
    dups = _find_duplicates_via_index(target_int, index, hashes_map, exclude_id=None, max_dist=PHASH_DUPLICATE_THRESHOLD)
    if dups:
        best_id = dups[0][0]
        return db.query(ImageModel.id, ImageModel.filename, ImageModel.phash).filter(ImageModel.id == best_id).first()
    return None


# === IoU ===
def _iou_xywh(a, b):
    ax1, ay1 = a["x"], a["y"]
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx1, by1 = b["x"], b["y"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / ua if ua > 0 else 0.0

def dedup_boxes(anns, iou_thr=0.5):
    if not anns:
        return anns
    srt = sorted(anns, key=lambda a: (a.get("confidence") or 0.0), reverse=True)
    keep = []
    for a in srt:
        if all(_iou_xywh(a, k) < iou_thr for k in keep):
            keep.append(a)
    return keep


# === Thumbnails ===
def _thumb_path(image_id: int) -> str:
    if not isinstance(image_id, int) or image_id <= 0:
        raise ValueError(f"invalid image_id: {image_id!r}")
    return os.path.join(THUMB_DIR, f"{image_id}.jpg")

def _remove_thumb(image_id: int):
    try:
        _remove_file_safe(_thumb_path(image_id))
    except ValueError:
        pass

def ensure_thumb(image_id: int, src_path: str) -> str:
    try:
        p = _thumb_path(image_id)
    except ValueError:
        log.warning("ensure_thumb: invalid image_id %r", image_id)
        return ""
    if os.path.exists(p):
        return p
    if not src_path or not os.path.exists(src_path):
        log.warning("ensure_thumb: source not found: %s", src_path)
        return ""
    try:
        img = Image.open(src_path).convert("RGB")
        img.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", THUMB_SIZE, (235, 235, 240))
        ox = (THUMB_SIZE[0] - img.width) // 2
        oy = (THUMB_SIZE[1] - img.height) // 2
        canvas.paste(img, (ox, oy))
        canvas.save(p, "JPEG", quality=82)
    except Exception as e:
        log.warning("thumb fail for %s: %s", image_id, e)
        return ""
    return p

_THUMB_POOL = None
_THUMB_POOL_LOCK = threading.Lock()

def _get_thumb_pool():
    global _THUMB_POOL
    if _THUMB_POOL is not None:
        return _THUMB_POOL
    with _THUMB_POOL_LOCK:
        if _THUMB_POOL is None:
            _THUMB_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumb-gen")
    return _THUMB_POOL

def _queue_thumb(image_id: int, src_path: str):
    try:
        _get_thumb_pool().submit(ensure_thumb, image_id, src_path)
    except Exception:
        log.exception("queue_thumb failed, falling back to sync")
        try:
            ensure_thumb(image_id, src_path)
        except Exception:
            pass

def shutdown_thumb_pool():
    global _THUMB_POOL
    if _THUMB_POOL is not None:
        try:
            _THUMB_POOL.shutdown(wait=True, cancel_futures=True)
        except Exception:
            log.exception("thumb pool shutdown failed")
        _THUMB_POOL = None


# === Duplicates cache ===
_DUPLICATES_CACHE = {}
_DUPLICATES_CACHE_LOCK = threading.Lock()
_DUPLICATES_CACHE_TTL = 30.0

def _compute_duplicate_ids(project_id: int, db, threshold: int = PHASH_DUPLICATE_THRESHOLD) -> set:
    index, hashes_map = _get_phash_index(db, project_id)
    if len(hashes_map) < 2:
        return set()
    parent = {iid: iid for iid in hashes_map}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    for iid, h_int in hashes_map.items():
        dups = _find_duplicates_via_index(h_int, index, hashes_map, exclude_id=iid, max_dist=threshold)
        for dup_id, _ in dups:
            union(iid, dup_id)
    groups = defaultdict(list)
    for iid in hashes_map:
        groups[find(iid)].append(iid)
    out = set()
    for ids in groups.values():
        if len(ids) >= 2:
            out.update(ids)
    return out

def _get_duplicate_ids_cached(project_id: int, db) -> set:
    now = time.monotonic()
    with _DUPLICATES_CACHE_LOCK:
        cached = _DUPLICATES_CACHE.get(project_id)
        if cached and (now - cached[0]) < _DUPLICATES_CACHE_TTL:
            return cached[1]
    ids = _compute_duplicate_ids(project_id, db)
    with _DUPLICATES_CACHE_LOCK:
        _DUPLICATES_CACHE[project_id] = (now, ids)
    return ids


# === Stats cache ===
_STATS_CACHE = {}
_STATS_CACHE_LOCK = threading.Lock()
_STATS_CACHE_TTL = 30.0

def _invalidate_stats_cache(project_id=None):
    with _STATS_CACHE_LOCK:
        if project_id is None:
            _STATS_CACHE.clear()
        else:
            _STATS_CACHE.pop(project_id, None)

def _compute_project_stats(project_id: int, db):
    total_q = (db.query(ImageModel.id).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)))
    total = total_q.count()
    if total == 0:
        return {"total_images": 0, "annotated_images": 0, "unannotated_images": 0,
                "total_boxes": 0, "avg_boxes": 0.0,
                "confidence": {"manual": 0, "low": 0, "mid": 0, "high": 0},
                "top_suspicious": [], "unannotated_sample": []}
    ids_subq = total_q.scalar_subquery() # [FIX:sawarning]
    agg = db.query(
        func.count(Annotation.id).label("cnt"),
        func.sum(case((Annotation.confidence.is_(None), 1), else_=0)).label("manual"),
        func.sum(case((Annotation.confidence < 0.5, 1), else_=0)).label("low"),
        func.sum(case((((Annotation.confidence >= 0.5) & (Annotation.confidence < 0.75)), 1), else_=0)).label("mid"),
        func.sum(case((Annotation.confidence >= 0.75, 1), else_=0)).label("high"),
    ).filter(Annotation.image_id.in_(ids_subq)).one()
    total_boxes = int(agg.cnt or 0)
    manual = int(agg.manual or 0); low = int(agg.low or 0)
    mid = int(agg.mid or 0); high = int(agg.high or 0)
    per_rows = (db.query(Annotation.image_id, func.count(Annotation.id), func.min(Annotation.confidence))
                  .filter(Annotation.image_id.in_(ids_subq))
                  .group_by(Annotation.image_id).all())
    per = {iid: cnt for iid, cnt, _ in per_rows}
    min_conf_by_img = {iid: mc for iid, _, mc in per_rows}
    annotated = len(per)
    suspicious_sorted = sorted(per.items(), key=lambda x: (min_conf_by_img.get(x[0]) if min_conf_by_img.get(x[0]) is not None else 1.0))[:10]
    unannotated_ids_q = (db.query(ImageModel.id).filter(ImageModel.project_id == project_id, ImageModel.is_deleted.is_(False)))
    if per:
        unannotated_ids_q = unannotated_ids_q.filter(~ImageModel.id.in_(per.keys()))
    unannotated_ids = [iid for (iid,) in unannotated_ids_q.limit(20).all()]
    wanted_ids = list({iid for iid, _ in suspicious_sorted} | set(unannotated_ids))
    metas = {}
    if wanted_ids:
        metas = {im.id: im for im in db.query(ImageModel).filter(ImageModel.id.in_(wanted_ids)).all()}
    top_suspicious = []
    for iid, cnt in suspicious_sorted:
        im = metas.get(iid)
        if not im: continue
        top_suspicious.append({"id": im.id, "filename": im.filename, "annotation_count": cnt, "min_confidence": min_conf_by_img.get(iid)})
    unannotated_sample = []
    for iid in unannotated_ids:
        im = metas.get(iid)
        if im: unannotated_sample.append({"id": im.id, "filename": im.filename})
    return {
        "total_images": total, "annotated_images": annotated, "unannotated_images": total - annotated,
        "total_boxes": total_boxes, "avg_boxes": (total_boxes / annotated) if annotated else 0.0,
        "confidence": {"manual": manual, "low": low, "mid": mid, "high": high},
        "top_suspicious": top_suspicious, "unannotated_sample": unannotated_sample,
    }

def get_project_stats_cached(project_id: int, db):
    now = time.monotonic()
    with _STATS_CACHE_LOCK:
        cached = _STATS_CACHE.get(project_id)
        if cached and (now - cached[0]) < _STATS_CACHE_TTL:
            return cached[1]
    data = _compute_project_stats(project_id, db)
    with _STATS_CACHE_LOCK:
        _STATS_CACHE[project_id] = (now, data)
    return data
