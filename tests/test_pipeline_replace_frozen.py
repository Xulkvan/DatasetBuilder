"""Pipeline replace без force_replace_frozen не должен затирать frozen."""
from datetime import datetime


def test_replace_requires_force_when_frozen_exist(local_app_client):
    from app import SessionLocal
    from models import Project, ImageModel, Annotation

    db = SessionLocal()
    try:
        p = Project(name="FrozenP", created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        im = ImageModel(project_id=p.id, filename="f.jpg",
                        path="/tmp/_f.jpg", width=640, height=640,
                        is_deleted=False, created_at=datetime.utcnow())
        db.add(im); db.commit(); db.refresh(im)
        db.add(Annotation(image_id=im.id, x=0.1, y=0.1, w=0.2, h=0.2,
                          label="pig", is_frozen=True))
        db.commit()
        pid = p.id
    finally:
        db.close()

    r = local_app_client.post(
        f"/api/projects/{pid}/pipeline/start",
        json={"mode": "replace", "stages": {"autolabel": False}},
    )
    assert r.status_code == 409, r.text
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("key") == "error.frozenAnnotationsExist"
