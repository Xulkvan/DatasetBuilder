"""[PATCH:STAGE5-T2] C2: CSV-эндпоинты stats.csv / files.csv / boxes.csv."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import app, SessionLocal, Project, ImageModel, Annotation

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


def _mk_ann(iid, **kw):
    db = SessionLocal()
    try:
        a = Annotation(image_id=iid,
                       x=kw.get("x", 0.1), y=kw.get("y", 0.1),
                       w=kw.get("w", 0.2), h=kw.get("h", 0.2),
                       label="pig",
                       behavior=kw.get("behavior"),
                       animal_id=kw.get("animal_id"))
        db.add(a); db.commit(); db.refresh(a)
        return a.id
    finally:
        db.close()


class TestStatsCsv:
    def test_stats_csv_exists(self):
        pid = _mk_project("t2_stats")
        iid = _mk_image(pid, "s.jpg")
        _mk_ann(iid)
        r = client.get(f"/api/projects/{pid}/stats.csv")
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "")
        assert "filename" in r.text

    def test_stats_csv_applies_filter(self):
        pid = _mk_project("t2_filter")
        iid1 = _mk_image(pid, "annot.jpg"); _mk_ann(iid1)
        _mk_image(pid, "empty.jpg")  # [PATCH:STAGE5-F841-FIX]
        r = client.get(f"/api/projects/{pid}/stats.csv?filter=unannotated")
        assert r.status_code == 200
        assert "empty.jpg" in r.text
        assert "annot.jpg" not in r.text


class TestFilesCsv:
    def test_files_csv_exists(self):
        pid = _mk_project("t2_files")
        _mk_image(pid, "f.jpg")
        r = client.get(f"/api/projects/{pid}/files.csv")
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "")
        assert "f.jpg" in r.text


class TestBoxesCsv:
    def test_boxes_csv_exists(self):
        pid = _mk_project("t2_boxes")
        iid = _mk_image(pid, "b.jpg")
        _mk_ann(iid, behavior="eat", animal_id=5)
        r = client.get(f"/api/projects/{pid}/boxes.csv")
        assert r.status_code == 200, r.text
        assert "eat" in r.text and "5" in r.text
