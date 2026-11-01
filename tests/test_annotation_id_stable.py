"""[STAGE5] Test: stable Annotation.id (upsert save_annotations).

Проверяет, что /api/images/{id}/annotations сохраняет Annotation.id
при повторных сохранениях (upsert вместо delete+create), корректно
обрабатывает новые/удалённые аннотации и keypoints, и игнорирует
чужие id (не «утаскивает» аннотации из других изображений).
"""
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


def _get_anns(iid):
    r = client.get(f"/api/images/{iid}/annotations")
    assert r.status_code == 200, r.text
    return r.json()


def _post_anns(iid, payload):
    r = client.post(f"/api/images/{iid}/annotations", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


class TestStableAnnotationId:
    def test_update_preserves_id(self):
        pid = _mk_project("idStable1")
        iid = _mk_image(pid)

        _post_anns(iid, [
            {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "pig"},
            {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1, "label": "pig"},
        ])
        anns = _get_anns(iid)
        assert len(anns) == 2
        ids_before = sorted(a["id"] for a in anns)

        payload = []
        for a in anns:
            payload.append({
                "id": a["id"],
                "x": a["x"] + 0.01,
                "y": a["y"], "w": a["w"], "h": a["h"],
                "label": a["label"],
                "confidence": a.get("confidence"),
                "frozen": a.get("frozen", False),
                "behavior": a.get("behavior"),
                "animal_id": a.get("animal_id"),
                "keypoints": a.get("keypoints", []),
            })
        _post_anns(iid, payload)

        anns_after = _get_anns(iid)
        ids_after = sorted(a["id"] for a in anns_after)
        assert ids_after == ids_before, f"ids changed: {ids_before} -> {ids_after}"

    def test_add_without_id_creates_new(self):
        pid = _mk_project("idStable2")
        iid = _mk_image(pid)

        _post_anns(iid, [
            {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "pig"},
        ])
        anns = _get_anns(iid)
        id1 = anns[0]["id"]

        _post_anns(iid, [
            {"id": id1, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "pig"},
            {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1, "label": "pig"},
        ])
        anns2 = _get_anns(iid)
        assert len(anns2) == 2
        ids2 = sorted(a["id"] for a in anns2)
        assert id1 in ids2
        assert any(a_id != id1 for a_id in ids2)

    def test_remove_annotation_without_keypoints_leak(self):
        pid = _mk_project("idStable3")
        iid = _mk_image(pid)

        _post_anns(iid, [
            {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "pig",
             "keypoints": [
                 {"name": "nose", "x": 0.12, "y": 0.12, "visibility": 1.0},
                 {"name": "withers", "x": 0.15, "y": 0.15, "visibility": 1.0},
             ]},
            {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1, "label": "pig",
             "keypoints": [
                 {"name": "nose", "x": 0.55, "y": 0.55, "visibility": 1.0},
             ]},
        ])
        anns = _get_anns(iid)
        assert len(anns) == 2
        kept_id = anns[0]["id"]
        dropped_id = anns[1]["id"]

        _post_anns(iid, [
            {"id": kept_id, "x": anns[0]["x"], "y": anns[0]["y"],
             "w": anns[0]["w"], "h": anns[0]["h"], "label": "pig",
             "keypoints": anns[0].get("keypoints", [])},
        ])

        anns2 = _get_anns(iid)
        assert len(anns2) == 1
        assert anns2[0]["id"] == kept_id

        db = SessionLocal()
        try:
            leftover = db.query(Keypoint).filter(
                Keypoint.annotation_id == dropped_id).count()
            assert leftover == 0, f"orphan keypoints: {leftover}"
        finally:
            db.close()

    def test_keypoints_upsert_in_place(self):
        pid = _mk_project("idStable4")
        iid = _mk_image(pid)

        _post_anns(iid, [
            {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "pig",
             "keypoints": [
                 {"name": "nose", "x": 0.12, "y": 0.12, "visibility": 1.0},
                 {"name": "withers", "x": 0.15, "y": 0.15, "visibility": 1.0},
             ]},
        ])
        anns = _get_anns(iid)
        ann_id = anns[0]["id"]

        _post_anns(iid, [
            {"id": ann_id, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "pig",
             "keypoints": [
                 {"name": "nose", "x": 0.13, "y": 0.13, "visibility": 1.0},
                 {"name": "withers", "x": 0.15, "y": 0.15, "visibility": 1.0},
                 {"name": "hip", "x": 0.25, "y": 0.25, "visibility": 1.0},
             ]},
        ])
        anns2 = _get_anns(iid)
        assert len(anns2) == 1
        assert anns2[0]["id"] == ann_id
        kps = anns2[0]["keypoints"]
        assert len(kps) == 3
        by_name = {k["name"]: k for k in kps}
        assert by_name["nose"]["x"] == 0.13
        assert "hip" in by_name

    def test_foreign_id_ignored(self):
        """id из другого изображения не должен «утащить» чужую аннотацию."""
        pid = _mk_project("idStable5")
        iid1 = _mk_image(pid, "a.jpg")
        iid2 = _mk_image(pid, "b.jpg")

        _post_anns(iid1, [
            {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2, "label": "pig"},
        ])
        foreign_id = _get_anns(iid1)[0]["id"]

        _post_anns(iid2, [
            {"id": foreign_id, "x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1, "label": "pig"},
        ])
        anns1 = _get_anns(iid1)
        anns2 = _get_anns(iid2)
        assert len(anns1) == 1
        assert anns1[0]["id"] == foreign_id
        assert len(anns2) == 1
        assert anns2[0]["id"] != foreign_id
