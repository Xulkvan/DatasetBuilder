"""[PATCH:STAGE1-C29] Optimistic locking via revision."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import app, SessionLocal, Project, ImageModel

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def _mk_image():
    db = SessionLocal()
    try:
        p = Project(name="c29_test", created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        im = ImageModel(project_id=p.id, filename="a.jpg",
                        path="/tmp/_c29_nope.jpg", width=640, height=640,
                        is_deleted=False)
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


def test_revision_conflict():
    iid = _mk_image()
    payload = [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "pig",
                "keypoints": []}]
    r = client.post(f"/api/images/{iid}/annotations?revision=1", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["revision"] == 2
    r = client.post(f"/api/images/{iid}/annotations?revision=1", json=payload)
    assert r.status_code == 409, r.text
    assert "staleRevision" in r.text


def test_no_revision_backward_compat():
    iid = _mk_image()
    payload = [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "pig",
                "keypoints": []}]
    r = client.post(f"/api/images/{iid}/annotations", json=payload)
    assert r.status_code == 200, r.text
    assert r.json().get("revision") == 2


def test_revision_increment_on_save():
    iid = _mk_image()
    payload = [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "pig"}]
    r = client.post(f"/api/images/{iid}/annotations", json=payload)
    assert r.status_code == 200
    assert r.json()["revision"] == 2
    r = client.post(f"/api/images/{iid}/annotations?revision=2", json=payload)
    assert r.status_code == 200
    assert r.json()["revision"] == 3
