"""[STAGE6:validator-tests] Реальные тесты валидатора разметки."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import (
    app, SessionLocal,
    Project, ImageModel, Annotation, Keypoint,
)

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


def _mk_image(pid, filename="a.jpg"):
    db = SessionLocal()
    try:
        im = ImageModel(project_id=pid, filename=filename,
                        path="/tmp/_nonexistent_" + filename,
                        width=640, height=640, is_deleted=False)
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


def _mk_ann(iid, x=0.1, y=0.1, w=0.2, h=0.2, aid=None, behavior=None):
    db = SessionLocal()
    try:
        a = Annotation(image_id=iid, x=x, y=y, w=w, h=h,
                       label="pig", animal_id=aid, behavior=behavior)
        db.add(a); db.commit(); db.refresh(a)
        return a.id
    finally:
        db.close()


class TestValidatorEndpoint:
    def test_returns_expected_shape(self):
        pid = _mk_project("valShape")
        iid = _mk_image(pid)
        _mk_ann(iid)
        r = client.get(f"/api/projects/{pid}/validate")
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("total_issues", "by_type", "issues", "unannotated",
                  "images_checked"):
            assert k in data
        assert data["images_checked"] == 1

    def test_small_box_detected(self):
        pid = _mk_project("valSmall")
        iid = _mk_image(pid)
        _mk_ann(iid, x=0.5, y=0.5, w=0.01, h=0.01)  # area < MIN_BOX_AREA
        r = client.get(f"/api/projects/{pid}/validate")
        data = r.json()
        assert data["by_type"].get("small_box", 0) >= 1

    def test_unannotated_image_reported(self):
        pid = _mk_project("valUn")
        _mk_image(pid, "empty1.jpg")
        _mk_image(pid, "empty2.jpg")
        r = client.get(f"/api/projects/{pid}/validate")
        data = r.json()
        assert len(data["unannotated"]) == 2

    def test_out_of_bounds_detected(self):
        pid = _mk_project("valOOB")
        iid = _mk_image(pid)
        _mk_ann(iid, x=0.9, y=0.9, w=0.2, h=0.2)  # x+w > 1
        r = client.get(f"/api/projects/{pid}/validate")
        data = r.json()
        assert data["by_type"].get("out_of_bounds", 0) >= 1


def test_pipeline_replace_clears_keypoints(monkeypatch):
    """[STAGE3] _stage_autolabel(mode='replace') удаляет keypoints до аннотаций."""
    from datetime import datetime
    from app import SessionLocal, Project, ImageModel, Annotation, Keypoint
    import services.pipeline_service as ps

    # Mock ML: cleanup в replace выполняется ДО инференса
    monkeypatch.setattr(ps, "get_active_model_path", lambda db: "/fake/model.pt")

    class _FakeModel:
        names = {0: "pig"}

    monkeypatch.setattr(ps, "_get_yolo_model", lambda path: _FakeModel())
    monkeypatch.setattr(ps, "_resolve_target_class_ids", lambda m, lbl: {0})

    db = SessionLocal()
    try:
        p = Project(
            name="pipeline_replace_kp_test",
            created_at=datetime.utcnow(),
            is_deleted=False,
            object_class="pig",
            object_class_source="list",
        )
        db.add(p); db.commit(); db.refresh(p)
        pid = p.id
        im = ImageModel(
            project_id=pid, filename="a.jpg",
            path="/tmp/_nonexistent_a.jpg",
            width=640, height=640, is_deleted=False,
        )
        db.add(im); db.commit(); db.refresh(im)
        a = Annotation(image_id=im.id, x=0.1, y=0.1, w=0.2, h=0.2, label="pig")
        db.add(a); db.commit(); db.refresh(a)
        aid = a.id
        db.add(Keypoint(annotation_id=aid, name="nose", x=0.5, y=0.5, visibility=1.0))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        result = ps._stage_autolabel(db, pid, mode="replace")
        assert result == "done", f"expected 'done', got {result!r}"
        remaining = db.query(Keypoint).filter(Keypoint.annotation_id == aid).count()
        assert remaining == 0, f"orphan keypoints after replace: {remaining}"
        remaining_anns = db.query(Annotation).filter(Annotation.id == aid).count()
        assert remaining_anns == 0, "old annotation not deleted"
    finally:
        db.close()
