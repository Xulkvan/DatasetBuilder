"""[STAGE6:validator-tests] Реальные тесты валидатора разметки."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import (
    app, SessionLocal,
    Project, ImageModel, Annotation, Keypoint,
)

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


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
                        path="/tmp/_nonexistent_" + filename,
                        width=640, height=640, is_deleted=False)
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


def _mk_ann(iid, x=0.1, y=0.1, w=0.2, h=0.2, aid=None, behavior=None):
    db = SessionLocal()
    try:
        a = Annotation(image_id=iid, x=x, y=y, w=w, h=h,
                       label="pig", animal_id=aid, behavior=behavior)
        db.add(a); db.commit(); db.refresh(a)
        return a.id
    finally:
        db.close()


class TestValidatorEndpoint:
    def test_returns_expected_shape(self):
        pid = _mk_project("valShape")
        iid = _mk_image(pid)
        _mk_ann(iid)
        r = client.get(f"/api/projects/{pid}/validate")
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("total_issues", "by_type", "issues", "unannotated",
                  "images_checked"):
            assert k in data
        assert data["images_checked"] == 1

    def test_small_box_detected(self):
        pid = _mk_project("valSmall")
        iid = _mk_image(pid)
        _mk_ann(iid, x=0.5, y=0.5, w=0.01, h=0.01)  # area < MIN_BOX_AREA
        r = client.get(f"/api/projects/{pid}/validate")
        data = r.json()
        assert data["by_type"].get("small_box", 0) >= 1

    def test_unannotated_image_reported(self):
        pid = _mk_project("valUn")
        _mk_image(pid, "empty1.jpg")
        _mk_image(pid, "empty2.jpg")
        r = client.get(f"/api/projects/{pid}/validate")
        data = r.json()
        assert len(data["unannotated"]) == 2

    def test_out_of_bounds_detected(self):
        pid = _mk_project("valOOB")
        iid = _mk_image(pid)
        _mk_ann(iid, x=0.9, y=0.9, w=0.2, h=0.2)  # x+w > 1
        r = client.get(f"/api/projects/{pid}/validate")
        data = r.json()
        assert data["by_type"].get("out_of_bounds", 0) >= 1
