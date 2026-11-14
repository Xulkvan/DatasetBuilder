"""[Patcher 9] Regression: sort in list_images applies BEFORE pagination.

Bug F-01: до патчера order_by применялся к `q` ПОСЛЕ того, как rows были
получены через `_page.all()`, поэтому window-count путь игнорировал sort
и всегда возвращал id_asc.
"""
from datetime import datetime

from fastapi.testclient import TestClient

from app import app, SessionLocal, Project, ImageModel

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def _mk_project(name):
    db = SessionLocal()
    try:
        p = Project(
            name=name, created_at=datetime.utcnow(),
            is_deleted=False, object_class="pig",
            object_class_source="list",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        return p.id
    finally:
        db.close()


def _mk_image(pid, filename):
    db = SessionLocal()
    try:
        im = ImageModel(
            project_id=pid, filename=filename,
            path="/tmp/_sort_" + filename,
            width=640, height=640, is_deleted=False,
        )
        db.add(im)
        db.commit()
        db.refresh(im)
        return im.id
    finally:
        db.close()


def _items(resp):
    body = resp.json()
    if isinstance(body, dict):
        return body.get("items", [])
    return body


def test_sort_by_name_asc_works():
    pid = _mk_project("sort_asc")
    _mk_image(pid, "z.jpg")
    _mk_image(pid, "a.jpg")
    _mk_image(pid, "m.jpg")

    r = client.get(f"/api/projects/{pid}/images?sort=name_asc&limit=2")
    assert r.status_code == 200, r.text
    names = [it["filename"] for it in _items(r)]
    assert names == ["a.jpg", "m.jpg"], names


def test_sort_by_name_desc_works():
    pid = _mk_project("sort_desc")
    _mk_image(pid, "a.jpg")
    _mk_image(pid, "z.jpg")

    r = client.get(f"/api/projects/{pid}/images?sort=name_desc&limit=2")
    assert r.status_code == 200, r.text
    names = [it["filename"] for it in _items(r)]
    assert names == ["z.jpg", "a.jpg"], names
