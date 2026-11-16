"""Lock-эндпоинты проверяют доступ к изображению."""
from datetime import datetime


def _seed_image(pid):
    from app import SessionLocal
    from models import ImageModel
    db = SessionLocal()
    try:
        im = ImageModel(project_id=pid, filename="l.jpg", path="/tmp/_l.jpg",
                        width=640, height=640, is_deleted=False,
                        created_at=datetime.utcnow())
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


def test_foreign_image_lock_endpoints_forbidden(ann_client):
    client, _ann_id, p1, _p2 = ann_client
    iid = _seed_image(p1)
    base = f"/api/images/{iid}/lock"
    assert client.get(base).status_code == 403
    assert client.post(base).status_code == 403
    assert client.post(base + "/heartbeat").status_code == 403
    assert client.delete(base).status_code == 403
