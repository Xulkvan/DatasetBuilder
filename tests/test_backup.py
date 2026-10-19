"""Интеграционные тесты для backup_project (правка #2).

Проверяет, что /api/projects/{id}/backup кладёт в annotations.json
не только bbox, но и behavior, animal_id и keypoints.
"""
from __future__ import annotations

import io
import json
import zipfile
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
                    is_deleted=False,
                    object_class="pig", object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        return p.id
    finally:
        db.close()


def _mk_image(project_id, filename="a.jpg"):
    db = SessionLocal()
    try:
        im = ImageModel(
            project_id=project_id, filename=filename,
            path="/tmp/_nonexistent_" + filename,
            width=640, height=640,
            is_deleted=False,
        )
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


def _mk_annotation(image_id, **kw):
    db = SessionLocal()
    try:
        a = Annotation(image_id=image_id,
                       x=kw.get("x", 0.1), y=kw.get("y", 0.1),
                       w=kw.get("w", 0.2), h=kw.get("h", 0.2),
                       label=kw.get("label", "pig"),
                       confidence=kw.get("confidence"),
                       is_frozen=kw.get("frozen", False),
                       behavior=kw.get("behavior"),
                       animal_id=kw.get("animal_id"))
        db.add(a); db.commit(); db.refresh(a)
        return a.id
    finally:
        db.close()


def _mk_keypoint(annotation_id, name, x, y, vis=1.0):
    db = SessionLocal()
    try:
        kp = Keypoint(annotation_id=annotation_id, name=name,
                      x=x, y=y, visibility=vis)
        db.add(kp); db.commit(); db.refresh(kp)
        return kp.id
    finally:
        db.close()


def _download_backup_annotations(pid):
    """Запускает backup и возвращает (annotations_dict, response_body)."""
    r = client.post("/api/projects/%d/backup" % pid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    filename = body["filename"]

    r2 = client.get("/api/projects/%d/backup/download/%s" % (pid, filename))
    assert r2.status_code == 200, r2.text

    with zipfile.ZipFile(io.BytesIO(r2.content)) as z:
        names = z.namelist()
        assert "annotations.json" in names
        assert "meta.json" in names
        raw = z.read("annotations.json").decode("utf-8")
        return json.loads(raw), body


class TestBackupPreservesAttributes:
    def test_behavior_and_animal_id_in_backup(self):
        """Правка #2: до неё behavior/animal_id в бэкап не попадали."""
        pid = _mk_project("backupAttrs")
        iid = _mk_image(pid, "a.jpg")
        _mk_annotation(iid, x=0.1, y=0.1, behavior="eat", animal_id=42)
        _mk_annotation(iid, x=0.5, y=0.5, behavior="stand", animal_id=7)

        anns, _body = _download_backup_annotations(pid)
        bucket = anns[str(iid)]
        assert len(bucket) == 2

        by_aid = {a["animal_id"]: a for a in bucket}
        assert set(by_aid.keys()) == {42, 7}
        assert by_aid[42]["behavior"] == "eat"
        assert by_aid[7]["behavior"] == "stand"

    def test_keypoints_in_backup(self):
        """Правка #2: до неё keypoints в бэкап не попадали."""
        pid = _mk_project("backupKP")
        iid = _mk_image(pid, "b.jpg")
        aid = _mk_annotation(iid, x=0.2, y=0.2)
        _mk_keypoint(aid, "nose", 0.25, 0.25, vis=1.0)
        _mk_keypoint(aid, "withers", 0.30, 0.28, vis=0.7)

        anns, _body = _download_backup_annotations(pid)
        bucket = anns[str(iid)]
        assert len(bucket) == 1
        kps = bucket[0]["keypoints"]
        assert len(kps) == 2
        by_name = {k["name"]: k for k in kps}
        assert by_name["nose"]["x"] == 0.25
        assert by_name["nose"]["visibility"] == 1.0
        assert by_name["withers"]["visibility"] == 0.7

    def test_annotation_without_attrs_has_empty_defaults(self):
        """У рамки без attrs/keypoints поля должны присутствовать
        (как None / []) — иначе распаковщик бэкапа сломается."""
        pid = _mk_project("backupEmpty")
        iid = _mk_image(pid, "c.jpg")
        _mk_annotation(iid, x=0.1, y=0.1)

        anns, _body = _download_backup_annotations(pid)
        a = anns[str(iid)][0]
        assert a["behavior"] is None
        assert a["animal_id"] is None
        assert a["keypoints"] == []

    def test_multiple_images_not_mixed(self):
        """Точки одной картинки не должны попасть в бэкап другой."""
        pid = _mk_project("backupMulti")
        i1 = _mk_image(pid, "x1.jpg")
        i2 = _mk_image(pid, "x2.jpg")
        a1 = _mk_annotation(i1, x=0.1, y=0.1, animal_id=1)
        a2 = _mk_annotation(i2, x=0.2, y=0.2, animal_id=2)
        _mk_keypoint(a1, "nose", 0.11, 0.11)
        _mk_keypoint(a2, "nose", 0.21, 0.21)
        _mk_keypoint(a2, "tail_base", 0.25, 0.25)

        anns, _body = _download_backup_annotations(pid)
        assert len(anns[str(i1)]) == 1
        assert len(anns[str(i2)]) == 1
        assert len(anns[str(i1)][0]["keypoints"]) == 1
        assert len(anns[str(i2)][0]["keypoints"]) == 2

    def test_backup_counts_match(self):
        """Счётчики в ответе backup_project должны быть консистентны."""
        pid = _mk_project("backupCounts")
        iid = _mk_image(pid, "d.jpg")
        _mk_annotation(iid)
        _mk_annotation(iid)
        _mk_annotation(iid)

        _anns, body = _download_backup_annotations(pid)
        assert body["images_count"] == 1
        assert body["annotations_count"] == 3
