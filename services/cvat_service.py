"""[STAGE2:cvat] CVAT XML 1.1 import/export."""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Optional
from xml.etree import ElementTree as ET

from sqlalchemy.orm import Session

from models import Project, ImageModel, Annotation, Keypoint

log = logging.getLogger("db")


def export_cvat_xml(db: Session, project_id: int) -> bytes:
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise ValueError("Project not found")
    imgs = (db.query(ImageModel)
              .filter(ImageModel.project_id == project_id,
                      ImageModel.is_deleted.is_(False))
              .order_by(ImageModel.id).all())
    # сохраняем регистр из проекта
    label = proj.object_class or "pig"

    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"
    meta = ET.SubElement(root, "meta")
    task = ET.SubElement(meta, "task")
    ET.SubElement(task, "name").text = proj.name or f"project_{project_id}"
    labels_el = ET.SubElement(task, "labels")
    lab = ET.SubElement(labels_el, "label")
    ET.SubElement(lab, "name").text = label
    ET.SubElement(lab, "color").text = "#0071e3"
    ET.SubElement(lab, "type").text = "any"

    from collections import defaultdict as _dd_cvat
    def _chunks_cvat(seq, n=500):
        for i in range(0, len(seq), n):
            yield seq[i:i + n]

    _img_ids = [img.id for img in imgs]
    _anns_by_img = _dd_cvat(list)
    for _c in _chunks_cvat(_img_ids):
        for _a in (db.query(Annotation)
                     .filter(Annotation.image_id.in_(_c))
                     .order_by(Annotation.id).all()):
            _anns_by_img[_a.image_id].append(_a)
    _all_ann_ids = [a.id for lst in _anns_by_img.values() for a in lst]
    _kps_by_ann = _dd_cvat(list)
    for _c in _chunks_cvat(_all_ann_ids):
        for _k in db.query(Keypoint).filter(Keypoint.annotation_id.in_(_c)).all():
            _kps_by_ann[_k.annotation_id].append(_k)

    for img in imgs:
        attrs = {"id": str(img.id), "name": img.filename or f"{img.id}.jpg",
                 "width": str(img.width or 640),
                 "height": str(img.height or 640)}
        img_el = ET.SubElement(root, "image", attrs)
        anns = _anns_by_img.get(img.id, [])
        for a in anns:
            xtl = round(a.x * (img.width or 640), 2)
            ytl = round(a.y * (img.height or 640), 2)
            xbr = round((a.x + a.w) * (img.width or 640), 2)
            ybr = round((a.y + a.h) * (img.height or 640), 2)
            box_attrs = {"label": label,
                         "xtl": str(xtl), "ytl": str(ytl),
                         "xbr": str(xbr), "ybr": str(ybr)}
            if a.animal_id is not None:
                box_attrs["occluded"] = "0"
            box = ET.SubElement(img_el, "box", box_attrs)
            if a.animal_id is not None:
                at = ET.SubElement(box, "attribute", {"name": "animal_id"})
                at.text = str(a.animal_id)
            if a.behavior:
                at2 = ET.SubElement(box, "attribute", {"name": "behavior"})
                at2.text = a.behavior
            # Скелет
            kps = _kps_by_ann.get(a.id, [])
            if kps:
                # CVAT 1.1: skeleton has ONLY label + points.
                # bbox stored as db_bbox attribute for DatasetBuilder round-trip.
                sk_el = ET.SubElement(img_el, "skeleton", {"label": "skeleton"})
                for kp in kps:
                    ET.SubElement(sk_el, "points",
                                  {"label": kp.name,
                                   "points": f"{round(kp.x*(img.width or 640),2)},{round(kp.y*(img.height or 640),2)}",
                                   "visibility": "1" if (kp.visibility or 0) >= 0.5 else "0"})
                _db_bbox_attr = ET.SubElement(sk_el, "attribute", {"name": "db_bbox"})
                _db_bbox_attr.text = f"{xtl},{ytl},{xbr},{ybr}"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)



from services.image_service import _iou_xywh


def parse_cvat_xml(xml_path: str) -> dict:
    """{basename_stem: [{x,y,w,h,label,animal_id,behavior,keypoints}]}"""
    out: dict = defaultdict(list)
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError:
        return dict(out)

    for img in root.findall("image"):
        try:
            iw = float(img.get("width") or 0)
            ih = float(img.get("height") or 0)
        except (TypeError, ValueError):
            iw = ih = 0
        name = img.get("name") or ""
        stem = os.path.splitext(os.path.basename(name))[0].lower()
        if not stem or iw <= 0 or ih <= 0:
            continue

        boxes: list[dict] = []
        skeletons: list[dict] = []

        # 1. Парсим <box>
        for box in img.findall("box"):
            try:
                xtl = float(box.get("xtl") or 0)
                ytl = float(box.get("ytl") or 0)
                xbr = float(box.get("xbr") or 0)
                ybr = float(box.get("ybr") or 0)
            except (TypeError, ValueError):
                continue
            w = (xbr - xtl) / iw
            h = (ybr - ytl) / ih
            if w <= 0 or h <= 0:
                continue
            rec = {"x": xtl / iw, "y": ytl / ih,
                   "w": w, "h": h,
                   "label": box.get("label") or "pig",
                   "keypoints": []}
            for attr in box.findall("attribute"):
                aname = attr.get("name")
                if aname == "animal_id" and attr.text:
                    try: rec["animal_id"] = int(attr.text)
                    except (TypeError, ValueError): pass
                elif aname == "behavior" and attr.text:
                    rec["behavior"] = attr.text
            boxes.append(rec)

        # 2. Парсим <skeleton>
        for sk in img.findall("skeleton"):
            # CVAT 1.1: skeleton has no xtl/ytl/xbr/ybr.
            # Compute bbox from points (or read db_bbox attribute for round-trip).
            _points_parsed = []
            for pt in sk.findall("points"):
                try:
                    p_str = pt.get("points", "")
                    px, py = map(float, p_str.split(","))
                    vis = 1.0 if pt.get("visibility", "1") in ("1", "true") else 0.0
                    _points_parsed.append({
                        "name": pt.get("label") or "nose",
                        "x": px / iw, "y": py / ih,
                        "visibility": vis,
                    })
                except (TypeError, ValueError):
                    continue
            xtl_raw = sk.get("xtl")
            if xtl_raw is not None:
                try:
                    xtl = float(xtl_raw)
                    ytl = float(sk.get("ytl") or 0)
                    xbr = float(sk.get("xbr") or 0)
                    ybr = float(sk.get("ybr") or 0)
                except (TypeError, ValueError):
                    continue
            else:
                _db_bbox_txt = None
                for _attr in sk.findall("attribute"):
                    if _attr.get("name") == "db_bbox" and _attr.text:
                        _db_bbox_txt = _attr.text
                        break
                if _db_bbox_txt:
                    try:
                        xtl, ytl, xbr, ybr = map(float, _db_bbox_txt.split(","))
                    except (TypeError, ValueError):
                        continue
                elif _points_parsed:
                    _pxs = [_p["x"] * iw for _p in _points_parsed]
                    _pys = [_p["y"] * ih for _p in _points_parsed]
                    xtl, ytl = min(_pxs), min(_pys)
                    xbr, ybr = max(_pxs), max(_pys)
                else:
                    continue
            w = (xbr - xtl) / iw
            h = (ybr - ytl) / ih
            if w <= 0 or h <= 0:
                continue
            sk_rec = {"x": xtl / iw, "y": ytl / ih,
                      "w": w, "h": h,
                      "label": sk.get("label") or "pig",
                      "keypoints": _points_parsed}
            skeletons.append(sk_rec)

        # 3. Мержим скелеты и боксы
        for sk in skeletons:
            best_box = None
            best_iou = 0.0
            for b in boxes:
                iou = _iou_xywh(sk, b)
                if iou > best_iou:
                    best_iou = iou
                    best_box = b
            if best_box and best_iou > 0.3:
                best_box["keypoints"].extend(sk["keypoints"])
            else:
                boxes.append(sk)

        for b in boxes:
            out[stem].append(b)
    return dict(out)
