"""[PATCH:STAGE5-T13] C13: behavior_audit передаёт project_id+db в
predict_behavior_from_keypoints (учёт проектных порогов)."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import (
    app, SessionLocal, Project, ImageModel, Annotation, Keypoint,
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
                        path="/tmp/_t13_" + filename,
                        width=640, height=640, is_deleted=False)
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


def _mk_ann(iid, behavior="eat"):
    db = SessionLocal()
    try:
        a = Annotation(image_id=iid, x=0.2, y=0.2, w=0.4, h=0.4,
                       label="pig", behavior=behavior, animal_id=1)
        db.add(a); db.commit(); db.refresh(a)
        return a.id
    finally:
        db.close()


def _add_kps(aid, nose_y=0.55):
    db = SessionLocal()
    try:
        db.add(Keypoint(annotation_id=aid, name="nose",
                        x=0.3, y=nose_y, visibility=1.0))
        db.add(Keypoint(annotation_id=aid, name="head_top",
                        x=0.35, y=0.30, visibility=1.0))
        db.add(Keypoint(annotation_id=aid, name="withers",
                        x=0.5, y=0.4, visibility=1.0))
        db.commit()
    finally:
        db.close()


class TestBehaviorAuditThresholds:
    def test_behavior_audit_uses_project_thresholds(self, monkeypatch):
        """C13: audit передаёт project_id и db (source of truth — сервер)."""
        pid = _mk_project("t13_audit")
        iid = _mk_image(pid)
        aid = _mk_ann(iid, behavior="eat")
        _add_kps(aid)

        captured = {}
        import routers.ml as ml_mod
        original = ml_mod.predict_behavior_from_keypoints

        def spy(*args, **kw):
            captured["project_id"] = kw.get("project_id")
            captured["db"] = kw.get("db")
            return original(*args, **kw)

        monkeypatch.setattr(ml_mod, "predict_behavior_from_keypoints", spy)

        r = client.post(f"/api/images/{iid}/behavior_audit", json={})
        assert r.status_code == 200, r.text

        assert captured.get("project_id") == pid, (
            f"audit не передаёт project_id в predict_behavior_from_keypoints: "
            f"captured={captured}"
        )
        assert captured.get("db") is not None, (
            f"audit не передаёт db в predict_behavior_from_keypoints: "
            f"captured={captured}"
        )

    def test_behavior_audit_returns_agreement(self):
        """Дополнительный sanity: shape ответа и чтение behavior из БД."""
        pid = _mk_project("t13_shape")
        iid = _mk_image(pid)
        aid = _mk_ann(iid, behavior="eat")
        _add_kps(aid, nose_y=0.55)

        r = client.post(f"/api/images/{iid}/behavior_audit", json={})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "total" in d and "agree" in d and "agreement" in d
        assert d["total"] == 1
        assert isinstance(d["rows"], list) and len(d["rows"]) == 1
        assert d["rows"][0]["human"] == "eat"
