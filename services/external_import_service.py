"""services/external_import_service.py — [PATCH:STAGE6-PART2-4.5]"""
from typing import Optional
import json, time, zipfile, tempfile, urllib.request, urllib.error
import re  # [PATCH:REFACTOR-FIX]
from config import MAX_UPLOAD_BYTES, MAX_IMPORT_BYTES
from fastapi import HTTPException
from services.url_safety import is_safe_external_url
from services.image_service import _remove_file_safe
import logging
log = logging.getLogger("db")


def _mask_exc(e) -> str:  # [PATCH:REFACTOR-FIX]
    """Маскирует query-параметры (возможные API-ключи) в тексте исключения."""
    try:
        msg = str(e) if e is not None else ""
    except Exception:
        return "<exception>"
    msg = re.sub(r'\?[^\s"\']+', '?***', msg)
    return msg[:200]


def _labelbox_to_coco(items: list, project_name: str) -> dict:
    coco = {"images": [], "annotations": [], "categories": []}
    cat_map = {}
    next_cat = 1
    next_ann = 1
    next_img = 1
    for item in items:
        data_row = item.get("data_row") or {}
        gkey = str(data_row.get("global_key") or data_row.get("external_id") or data_row.get("id") or "")  # [PATCH:STAGE1-LABELBOX-FALLBACK]
        if not gkey:
            continue
        media_attrs = data_row.get("media_attributes") or {}
        w = int(media_attrs.get("width") or 0)
        h = int(media_attrs.get("height") or 0)
        img_id = next_img
        next_img += 1
        coco["images"].append({"id": img_id, "file_name": gkey, "width": w, "height": h})
        projects = item.get("projects") or {}
        for pid, proj in projects.items():
            labels = proj.get("labels") or []
            for label in labels:
                anns = label.get("annotations") or {}
                objects = anns.get("objects") or []
                for obj in objects:
                    name = (obj.get("name") or "object").strip()
                    if name not in cat_map:
                        cat_map[name] = next_cat
                        coco["categories"].append({"id": next_cat, "name": name})
                        next_cat += 1
                    cid = cat_map[name]
                    bbox = obj.get("bounding_box") or {}
                    if bbox:
                        left = float(bbox.get("left") or 0)
                        top = float(bbox.get("top") or 0)
                        bw = float(bbox.get("width") or 0)
                        bh = float(bbox.get("height") or 0)
                    else:
                        poly = (obj.get("polygon") or [])
                        if not poly:
                            continue
                        xs = [float(p.get("x") or 0) for p in poly]
                        ys = [float(p.get("y") or 0) for p in poly]
                        left, top = min(xs), min(ys)
                        bw, bh = max(xs) - left, max(ys) - top
                    if bw <= 0 or bh <= 0:
                        continue
                    coco["annotations"].append({
                        "id": next_ann, "image_id": img_id, "category_id": cid,
                        "bbox": [left, top, bw, bh], "area": bw * bh, "iscrowd": 0,
                    })
                    next_ann += 1
    return coco


def _scale_to_coco(items: list) -> dict:
    coco = {"images": [], "annotations": [], "categories": []}
    cat_map = {}
    next_cat = 1
    next_ann = 1
    next_img = 1
    for it in items:
        ref = str(it.get("reference_id") or it.get("external_id") or it.get("id") or "")  # [PATCH:STAGE1-SCALE-REF-STR]
        img_id = next_img
        next_img += 1
        coco["images"].append({
            "id": img_id, "file_name": ref,
            "width": int(it.get("width") or 0), "height": int(it.get("height") or 0),
        })
        for ann in (it.get("annotations") or []):
            label = (ann.get("label") or ann.get("annotation_label") or "object").strip()
            if label not in cat_map:
                cat_map[label] = next_cat
                coco["categories"].append({"id": next_cat, "name": label})
                next_cat += 1
            cid = cat_map[label]
            geom = ann.get("geometry") or {}
            if geom.get("type") == "box" or ("x" in geom and "width" in geom):
                left = float(geom.get("x") or 0)
                top = float(geom.get("y") or 0)
                bw = float(geom.get("width") or 0)
                bh = float(geom.get("height") or 0)
            elif isinstance(geom.get("vertices"), list):
                xs = [float(v.get("x") or 0) for v in geom["vertices"]]
                ys = [float(v.get("y") or 0) for v in geom["vertices"]]
                if not xs or not ys:
                    continue
                left, top = min(xs), min(ys)
                bw, bh = max(xs) - left, max(ys) - top
            else:
                continue
            if bw <= 0 or bh <= 0:
                continue
            coco["annotations"].append({
                "id": next_ann, "image_id": img_id, "category_id": cid,
                "bbox": [left, top, bw, bh], "area": bw * bh, "iscrowd": 0,
            })
            next_ann += 1
    return coco


def _coco_to_zip(coco: dict, image_urls: dict, out_path: str,
                  max_per_image: int | None = None) -> dict:
    # [STAGE1.6:coco-limit] Раньше скачивали без лимита: 100GB URL
    # мог положить сервер. Теперь через _download_to_file(max_bytes=50MB)
    # и превышение уходит в `missing`, не ломая весь импорт.
    if max_per_image is None:
        max_per_image = MAX_UPLOAD_BYTES
    downloaded = 0
    missing = []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_annotations.coco.json", json.dumps(coco, ensure_ascii=False, indent=2))
        for im in coco["images"]:
            fname = im["file_name"]
            url = image_urls.get(fname)
            if not url:
                missing.append(fname)
                continue
            # [STAGE5:ssrf-coco]
            if not is_safe_external_url(url):
                missing.append(fname)
                continue
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp.close()
            try:
                _download_to_file(url, tmp.name, max_bytes=max_per_image)
                with open(tmp.name, "rb") as _cf:
                    data = _cf.read()
                z.writestr(fname, data)
                downloaded += 1
            except HTTPException:
                missing.append(fname)
            except Exception:
                log.exception("download failed for %s", fname)
                missing.append(fname)
            finally:
                _remove_file_safe(tmp.name)
    return {"downloaded": downloaded, "missing": missing}

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
# Rate limiter moved to services/rate_limiter.py


# [PATCH:STAGE6-F15-C18] moved to services/errors.py

def _download_to_file(url: str, dest: str, timeout: int = 900,
                       extra_headers: Optional[dict] = None,
                       retries: int = 2,
                       max_bytes: int | None = None) -> None:
    """V7.9.3: 3 попытки + exponential backoff (1.5s, 3s).

    [STAGE1.5:download-limit] max_bytes (default MAX_IMPORT_BYTES)
    — жёсткий лимит размера, чтобы import_url не мог залить 100GB.
    4xx (кроме 429) не retry-им — это не сетевой сбой, а наша ошибка.
    """
    if max_bytes is None:
        max_bytes = MAX_IMPORT_BYTES
    # [STAGE5:ssrf-download]
    if not is_safe_external_url(url):
        raise HTTPException(400, "URL ведёт во внутреннюю сеть (SSRF protection)")
    headers = {"User-Agent": "DatasetBuilder/7.9.3"}
    if extra_headers:
        headers.update(extra_headers)
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                # [STAGE1.5:download-limit] Content-Length проверка
                _cl = r.headers.get("Content-Length")
                if _cl:
                    try:
                        if int(_cl) > max_bytes:
                            raise HTTPException(413, f"Файл больше {max_bytes // (1024*1024)} МБ")
                    except (ValueError, TypeError):
                        pass
                with open(dest, "wb") as f:
                    total = 0
                    while True:
                        chunk = r.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise HTTPException(413, f"Файл больше {max_bytes // (1024*1024)} МБ")
                        f.write(chunk)
            return
        except HTTPException:
            # [STAGE1.5:download-limit] не retry-им нашу явную проверку
            raise
        except urllib.error.HTTPError as e:
            last_exc = e
            if 400 <= e.code < 500 and e.code != 429:
                raise
        except Exception as e:
            last_exc = e
        if attempt < retries:
            delay = 1.5 * (2 ** attempt)
            log.warning("_download_to_file attempt %d failed: %s; retry in %.1fs",
                        attempt + 1, _mask_exc(last_exc), delay)
            time.sleep(delay)
    raise last_exc

# V7.8.4: общий скелет для внешних импортёров — временный zip + проверка






def _http_get_json(url: str, headers: dict, timeout: int = 120,
                    retries: int = 2) -> dict:
    """V7.9.3: retries + backoff. 4xx не retry-им."""
    # [STAGE5:ssrf-http-get]
    if not is_safe_external_url(url):
        raise HTTPException(400, "URL ведёт во внутреннюю сеть (SSRF protection)")
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_exc = e
            if 400 <= e.code < 500 and e.code != 429:
                raise
        except Exception as e:
            last_exc = e
        if attempt < retries:
            delay = 1.5 * (2 ** attempt)
            log.warning("_http_get_json attempt %d failed: %s; retry in %.1fs",
                        attempt + 1, _mask_exc(last_exc), delay)
            time.sleep(delay)
    raise last_exc
# [PATCH:STAGE6-PART2] moved _http_post_json

def _http_post_json(url: str, headers: dict, body: dict, timeout: int = 120,
                     retries: int = 2) -> dict:
    """V7.9.3: retries + backoff. 4xx не retry-им — payload/ключа не поправим."""
    # [STAGE5:ssrf-http-post]
    if not is_safe_external_url(url):
        raise HTTPException(400, "URL ведёт во внутреннюю сеть (SSRF protection)")
    data = json.dumps(body).encode("utf-8")
    hdr = {"Content-Type": "application/json", "User-Agent": "DatasetBuilder/7.9.3"}
    hdr.update(headers or {})
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=hdr, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_exc = e
            if 400 <= e.code < 500 and e.code != 429:
                raise
        except Exception as e:
            last_exc = e
        if attempt < retries:
            delay = 1.5 * (2 ** attempt)
            log.warning("_http_post_json attempt %d failed: %s; retry in %.1fs",
                        attempt + 1, _mask_exc(last_exc), delay)
            time.sleep(delay)
    raise last_exc