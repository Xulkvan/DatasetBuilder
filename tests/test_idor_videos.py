"""Видео-эндпоинты legacy app.py проверяют доступ к проекту видео."""
from datetime import datetime


def _seed_video(pid):
    from app import SessionLocal
    from models import Video
    db = SessionLocal()
    try:
        v = Video(project_id=pid, filename="v.mp4", path="/tmp/_v.mp4",
                  is_deleted=False, created_at=datetime.utcnow())
        db.add(v); db.commit(); db.refresh(v)
        return v.id
    finally:
        db.close()


def test_foreign_video_endpoints_forbidden(ann_client):
    client, _ann_id, p1, _p2 = ann_client
    vid = _seed_video(p1)
    assert client.get(f"/api/videos/{vid}").status_code == 403
    assert client.get(f"/api/videos/{vid}/track/status").status_code == 403
    assert client.post(f"/api/videos/{vid}/track/stop").status_code == 403
    assert client.get(f"/api/videos/{vid}/track/metrics").status_code == 403
    assert client.delete(f"/api/videos/{vid}").status_code == 403
    assert client.get(f"/api/projects/{p1}/videos").status_code == 403
