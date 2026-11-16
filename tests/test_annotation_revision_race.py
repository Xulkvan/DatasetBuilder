"""CAS по revision: параллельное сохранение не теряет данные, stale → 409."""
from datetime import datetime


def _seed():
    from app import SessionLocal
    from models import Project, ImageModel
    db = SessionLocal()
    try:
        p = Project(name="RevP", created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        im = ImageModel(project_id=p.id, filename="r.jpg", path="/tmp/_r.jpg",
                        width=640, height=640, is_deleted=False,
                        revision=1, created_at=datetime.utcnow())
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


def _ann(x=0.1, **kw):
    d = {"x": x, "y": 0.1, "w": 0.2, "h": 0.2, "label": "pig",
         "confidence": 0.9, "frozen": False}
    d.update(kw)
    return d


def test_stale_revision_returns_409(local_app_client):
    iid = _seed()
    url = f"/api/images/{iid}/annotations?revision=1"
    r1 = local_app_client.post(url, json=[_ann()])
    assert r1.status_code == 200, r1.text
    r2 = local_app_client.post(url, json=[_ann(x=0.3)])
    assert r2.status_code == 409, r2.text


def test_unconditional_increment_without_revision(local_app_client):
    iid = _seed()
    url = f"/api/images/{iid}/annotations"
    assert local_app_client.post(url, json=[_ann()]).status_code == 200
    assert local_app_client.post(url, json=[_ann(x=0.2)]).status_code == 200


def test_foreign_annotation_id_rejected(local_app_client):
    iid = _seed()
    r = local_app_client.post(
        f"/api/images/{iid}/annotations",
        json=[_ann(id=999999)],
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail")
    if isinstance(detail, dict):
        assert detail.get("key") == "error.annotationNotFound"
