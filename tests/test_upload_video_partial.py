"""[PATCH:STAGE5-T14] F-16: upload_video per-frame commit — при сбое на
N-м кадре первые N-1 сохраняются."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import app, SessionLocal, Project, ImageModel

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


class TestUploadVideoPartial:
    def test_upload_video_partial_failure_keeps_previous_frames(
            self, tmp_path, monkeypatch):
        from PIL import Image as _PILImage

        pid = _mk_project("t14_partial")

        # 5 реальных jpg-файлов
        frame_paths = []
        for i in range(5):
            fp = tmp_path / f"frame_{i:04d}.jpg"
            _PILImage.new("RGB", (64, 64),
                          (i * 40, 100, 100)).save(fp, format="JPEG")
            frame_paths.append(str(fp))

        monkeypatch.setattr(
            "app._probe_video",
            lambda p: {"fps": 25.0, "duration": 1.0, "frame_count": 5},
        )
        monkeypatch.setattr(
            "app._extract_frames",
            lambda p, d, fps, progress_cb=None: list(frame_paths),
        )
        monkeypatch.setattr("app._check_ffmpeg", lambda: (True, ""))

        # Эмулируем падение на 5-м ImageModel-инстансе внутри loop
        call_count = {"n": 0}
        original_init = ImageModel.__init__

        def failing_init(self, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 5:
                raise RuntimeError("Simulated failure on frame 4")
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(ImageModel, "__init__", failing_init)

        video_bytes = b"fake video content" * 100
        r = client.post(
            f"/api/projects/{pid}/videos/upload",
            files={"file": ("v.mp4", video_bytes, "video/mp4")},
            data={"extract_fps": "2.0"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["images_count"] == 4, (
            f"ожидали 4 сохранённых кадра, got {data}"
        )

        db = SessionLocal()
        try:
            count = db.query(ImageModel).filter(
                ImageModel.project_id == pid,
                ImageModel.is_deleted.is_(False),
            ).count()
            assert count == 4, f"в БД {count} кадров, ожидали 4"
        finally:
            db.close()
