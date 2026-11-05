"""[PATCH:STAGE5-T12] C28: pipeline не тратит запросы на images без video_id."""
from datetime import datetime

from app import SessionLocal, Project, ImageModel, Annotation, Keypoint


def test_pipeline_behavior_skips_motion_for_static_images(monkeypatch):
    import services.pipeline_service as ps

    call_count = {"n": 0}

    def fake_check_motion(db, image_id, animal_id):
        call_count["n"] += 1
        return None

    monkeypatch.setattr(ps, "_check_motion", fake_check_motion)

    db = SessionLocal()
    try:
        p = Project(name="t12_pipe", created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        pid = p.id

        # 5 статических изображений без video_id
        for k in range(5):
            im = ImageModel(project_id=pid, filename=f"static_{k}.jpg",
                            path=f"/tmp/_t12_s{k}.jpg",
                            width=640, height=640, is_deleted=False,
                            video_id=None)
            db.add(im); db.commit(); db.refresh(im)
            a = Annotation(image_id=im.id, x=0.1, y=0.1, w=0.2, h=0.2,
                           label="pig", animal_id=k + 1)
            db.add(a); db.commit(); db.refresh(a)
            db.add(Keypoint(annotation_id=a.id, name="nose",
                            x=0.15, y=0.15, visibility=1.0))
            db.add(Keypoint(annotation_id=a.id, name="withers",
                            x=0.3, y=0.4, visibility=1.0))
        db.commit()
    finally:
        db.close()

    ps.PIPELINE_STOP.clear()
    db = SessionLocal()
    try:
        result = ps._stage_behavior(db, pid, mode="add")
        assert result == "done", f"expected done, got {result!r}"
        assert call_count["n"] == 0, (
            f"_check_motion вызван {call_count['n']} раз(а) для "
            f"images без video_id — C28 не применён"
        )
    finally:
        db.close()
