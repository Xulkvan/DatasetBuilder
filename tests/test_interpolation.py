"""[STAGE1-D:test-interpolation] Тесты /api/projects/{id}/interpolate."""
from datetime import datetime
from fastapi.testclient import TestClient
from app import app, SessionLocal, Project, ImageModel, Annotation, Video

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def _mk_project(name):
    db = SessionLocal()
    try:
        p = Project(name=name, created_at=datetime.utcnow(), is_deleted=False,
                    object_class="pig", object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        return p.id
    finally:
        db.close()


def _mk_video(pid):
    db = SessionLocal()
    try:
        v = Video(project_id=pid, filename="v.mp4", path="/tmp/_nonexist.mp4",
                  fps=25.0, extract_fps=2.0, is_deleted=False)
        db.add(v); db.commit(); db.refresh(v)
        return v.id
    finally:
        db.close()


def _mk_frame(pid, vid, fidx):
    db = SessionLocal()
    try:
        im = ImageModel(project_id=pid, filename=f"f{fidx}.jpg",
                        path=f"/tmp/_nonexist_f{fidx}.jpg",
                        width=640, height=640, is_deleted=False,
                        video_id=vid, frame_index=fidx)
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


def _mk_ann(iid, x, y, w, h, aid=1):
    db = SessionLocal()
    try:
        a = Annotation(image_id=iid, x=x, y=y, w=w, h=h, label="pig",
                       confidence=None, is_frozen=False, behavior="eat", animal_id=aid)
        db.add(a); db.commit(); db.refresh(a)
        return a.id
    finally:
        db.close()


class TestInterpolation:
    def test_interpolates_middle_frames(self):
        pid = _mk_project("interpP")
        vid = _mk_video(pid)
        f1 = _mk_frame(pid, vid, 0)
        _mk_frame(pid, vid, 1)  # [STAGE6:test-fixes-2-interp] промежуточный
        f2 = _mk_frame(pid, vid, 2)
        a1 = _mk_ann(f1, 0.1, 0.1, 0.2, 0.2)
        a2 = _mk_ann(f2, 0.3, 0.3, 0.2, 0.2)
        r = client.post(f"/api/projects/{pid}/interpolate", json={
            "animal_id": 1, "from_ann_id": a1, "to_ann_id": a2,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["interpolated_frames"] == 1
        assert body["from_frame"] == 0
        assert body["to_frame"] == 2

    def test_invalid_range(self):
        pid = _mk_project("interpBad")
        r = client.post(f"/api/projects/{pid}/interpolate", json={
            "animal_id": 1, "from_ann_id": 999, "to_ann_id": 998,
        })
        assert r.status_code == 400
