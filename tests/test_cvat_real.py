"""[PATCH:STAGE5-T8] C7+C10: CVAT XML 1.1 — skeleton без xtl/ytl."""
from datetime import datetime
from xml.etree import ElementTree as ET

from app import (
    SessionLocal, Project, ImageModel, Annotation, Keypoint,
)
from services.cvat_service import export_cvat_xml, parse_cvat_xml


def _mk_project(name):
    db = SessionLocal()
    try:
        p = Project(name=name, created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        return p.id
    finally:
        db.close()


def _mk_image(pid, filename="a.jpg"):
    db = SessionLocal()
    try:
        im = ImageModel(project_id=pid, filename=filename,
                        path="/tmp/_t8_" + filename,
                        width=640, height=480, is_deleted=False)
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


def _mk_ann(iid):
    db = SessionLocal()
    try:
        a = Annotation(image_id=iid, x=0.1, y=0.1, w=0.2, h=0.2,
                       label="pig", behavior="eat", animal_id=42)
        db.add(a); db.commit(); db.refresh(a)
        return a.id
    finally:
        db.close()


def _mk_kp(aid, name, x, y, vis=1.0):
    db = SessionLocal()
    try:
        kp = Keypoint(annotation_id=aid, name=name, x=x, y=y, visibility=vis)
        db.add(kp); db.commit(); db.refresh(kp)
        return kp.id
    finally:
        db.close()


class TestCvatRoundTrip:
    def test_cvat_round_trip_with_real_format(self):
        pid = _mk_project("t8_rt")
        iid = _mk_image(pid, "pic.jpg")
        aid = _mk_ann(iid)
        _mk_kp(aid, "nose", 0.15, 0.15, 1.0)
        _mk_kp(aid, "withers", 0.20, 0.18, 0.9)

        db = SessionLocal()
        try:
            xml_bytes = export_cvat_xml(db, pid)
        finally:
            db.close()

        assert b"<annotations>" in xml_bytes
        root = ET.fromstring(xml_bytes)
        img_el = root.find("image")
        assert img_el is not None
        skel = img_el.find("skeleton")
        assert skel is not None, "skeleton отсутствует в экспорте"
        # CVAT 1.1: skeleton НЕ должен иметь xtl/ytl/xbr/ybr
        for attr in ("xtl", "ytl", "xbr", "ybr"):
            assert skel.get(attr) is None, (
                f"skeleton не должен содержать {attr} (CVAT 1.1)"
            )
        points = skel.findall("points")
        names = {p.get("label") for p in points}
        assert names == {"nose", "withers"}
        # db_bbox сохраняется для round-trip
        db_bbox_attr = None
        for attr in skel.findall("attribute"):
            if attr.get("name") == "db_bbox":
                db_bbox_attr = attr.text
                break
        assert db_bbox_attr is not None
        assert len(db_bbox_attr.split(",")) == 4

    def test_cvat_import_real_skeleton_no_xtl(self, tmp_path):
        """Реальный CVAT 1.1: skeleton без bbox-атрибутов -> bbox из points."""
        xml = """<?xml version="1.0" encoding="utf-8"?>
<annotations>
  <version>1.1</version>
  <image id="0" name="real.jpg" width="640" height="480">
    <box label="pig" xtl="64.0" ytl="48.0" xbr="192.0" ybr="144.0"/>
    <skeleton label="skeleton">
      <points label="nose" points="96.0,96.0" visibility="1"/>
      <points label="withers" points="128.0,120.0" visibility="1"/>
      <points label="hip" points="160.0,120.0" visibility="0"/>
    </skeleton>
  </image>
</annotations>"""
        p = tmp_path / "real_cvat.xml"
        p.write_text(xml, encoding="utf-8")
        parsed = parse_cvat_xml(str(p))
        assert "real" in parsed
        boxes = parsed["real"]
        assert len(boxes) >= 1
        with_kp = [b for b in boxes if b.get("keypoints")]
        assert with_kp, f"keypoints не найдены: {boxes}"
        kp_names = {k["name"] for k in with_kp[0]["keypoints"]}
        assert "nose" in kp_names
        assert "withers" in kp_names
        # bbox вычислен из точек: min_x=96/640=0.15
        b = with_kp[0]
        assert abs(b["x"] - 96.0 / 640) < 0.01
        assert abs(b["y"] - 96.0 / 480) < 0.01
