"""[STAGE6:test-versions] Diff версий с keypoints/behaviors."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import (
    app, SessionLocal,
    Project, ImageModel, Annotation, Keypoint,
)

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def test_versions_diff_includes_kp_beh():
    db = SessionLocal()
    try:
        p = Project(name="vdtest", created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        pid = p.id
        im = ImageModel(project_id=pid, filename="a.jpg",
                        path="/tmp/_nope.jpg", width=640, height=640,
                        is_deleted=False)
        db.add(im); db.commit(); db.refresh(im)
        iid = im.id
        a = Annotation(image_id=iid, x=0.1, y=0.1, w=0.2, h=0.2,
                       label="pig", behavior="eat")
        db.add(a); db.commit(); db.refresh(a)
        db.add(Keypoint(annotation_id=a.id, name="nose",
                        x=0.15, y=0.15, visibility=1.0))
        db.commit()
    finally:
        db.close()

    v1 = client.post(f"/api/projects/{pid}/version").json()

    db = SessionLocal()
    try:
        db.add(Annotation(image_id=iid, x=0.5, y=0.5, w=0.1, h=0.1,
                          label="pig", behavior="stand"))
        db.commit()
    finally:
        db.close()

    v2 = client.post(f"/api/projects/{pid}/version").json()

    r = client.get(
        f"/api/projects/{pid}/versions/diff"
        f"?hash1={v1['hash']}&hash2={v2['hash']}"
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert "keypoints_added" in d
    assert "behaviors_added" in d
    assert d["behaviors_added"] >= 1
