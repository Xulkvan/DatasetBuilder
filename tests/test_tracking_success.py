"""[STAGE-2-PATCH-V3] Tracking returns status=done (regression for track_to_aid NameError).

Мокает:
  * app.get_active_model_path  -- иначе video_track_start кидает 501
  * services.track_service._get_yolo_model -- фейковая модель с IoU=1.0
"""
import importlib
import time
from datetime import datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def ctx(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "track.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))

    import services.track_service as ts

    class _FakeTensor:
        def __init__(self, arr):
            self._arr = np.asarray(arr)

        def cpu(self):
            return self

        def numpy(self):
            return self._arr

    class _FakeBoxes:
        def __init__(self):
            # Пиксельные координаты совпадают с аннотацией (0.1,0.1,0.2,0.2)*640
            self.xyxy = _FakeTensor([[64.0, 64.0, 192.0, 192.0]])
            self.id = _FakeTensor([1])

    class _FakeResult:
        def __init__(self):
            self.boxes = _FakeBoxes()

    class _FakeModel:
        def track(self, source, **kw):
            for _ in source:
                yield _FakeResult()

        @property
        def predictor(self):
            return None

        @predictor.setter
        def predictor(self, v):
            pass

    monkeypatch.setattr(ts, "_get_yolo_model", lambda p: _FakeModel())

    import app as app_mod
    importlib.reload(app_mod)
    # ВАЖНО: video_track_start проверяет get_active_model_path ДО запуска
    # _track_worker. Без мока -- 501 "Нет активной YOLO-модели".
    monkeypatch.setattr(
        app_mod, "get_active_model_path", lambda db: "/fake/model.pt",
    )
    return TestClient(app_mod.app), tmp_path


def test_tracking_completes_with_done_status(ctx):
    """Регрессия: track_to_aid NameError -> status=error. После фикса -- status=done."""
    from app import SessionLocal, Project, Video, ImageModel, Annotation
    client, tmp = ctx

    db = SessionLocal()
    try:
        p = Project(name="trk", created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        pid = p.id
        v = Video(project_id=pid, filename="v.mp4",
                  path=str(tmp / "v.mp4"), fps=25.0,
                  extract_fps=2.0, is_deleted=False)
        db.add(v); db.commit(); db.refresh(v)
        vid = v.id
        for i in range(3):
            fp = tmp / f"f{i}.jpg"
            from PIL import Image
            Image.new("RGB", (64, 64), (0, 0, 0)).save(fp)
            im = ImageModel(project_id=pid, filename=f"f{i}.jpg",
                            path=str(fp), width=640, height=640,
                            is_deleted=False, video_id=vid, frame_index=i)
            db.add(im); db.commit(); db.refresh(im)
            db.add(Annotation(image_id=im.id, x=0.1, y=0.1, w=0.2, h=0.2,
                              label="pig"))
        db.commit()
    finally:
        db.close()

    r = client.post(f"/api/videos/{vid}/track")
    assert r.status_code in (200, 409), r.text

    s = None
    for _ in range(100):
        r = client.get(f"/api/videos/{vid}/track/status")
        s = r.json()
        if s["status"] in ("done", "error", "stopped"):
            break
        time.sleep(0.1)

    assert s is not None
    assert s["status"] == "done", (
        f"tracking failed: status={s['status']} message={s.get('message')}"
    )
    assert s["assignments"] >= 1
