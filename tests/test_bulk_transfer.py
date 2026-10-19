"""Интеграционные тесты для bulk copy (правка #5).

Проверяет, что /api/images/bulk_copy_to_project сохраняет behavior,
animal_id и keypoints при копировании изображения в другой проект.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import (
    app, SessionLocal, UPLOAD_DIR,
    Project, ImageModel, Annotation, Keypoint,
)

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def _mk_real_image_file():
    """bulk_copy делает shutil.copyfile — нужен реальный файл на диске."""
    p = Path(UPLOAD_DIR) / ("test_" + uuid.uuid4().hex[:8] + ".jpg")
    img = Image.new("RGB", (64, 64), (128, 128, 128))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    p.write_bytes(buf.getvalue())
    return str(p)


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


def _mk_image(project_id, filename=None):
    filename = filename or ("img_" + uuid.uuid4().hex[:6] + ".jpg")
    path = _mk_real_image_file()
    db = SessionLocal()
    try:
        im = ImageModel(
            project_id=project_id, filename=filename, path=path,
            width=640, height=640, is_deleted=False,
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


def _fetch_annotations(image_id):
    r = client.get("/api/images/%d/annotations" % image_id)
    assert r.status_code == 200, r.text
    return r.json()


def _fetch_keypoints(image_id):
    r = client.get("/api/images/%d/keypoints_by_index" % image_id)
    assert r.status_code == 200, r.text
    return r.json()


def _images_of_project(pid):
    r = client.get("/api/projects/%d/images?limit=0" % pid)
    assert r.status_code == 200, r.text
    body = r.json()
    if isinstance(body, dict):
        return body.get("items", [])
    return body


class TestBulkCopyPreservesAttributes:
    def test_behavior_and_animal_id_copied(self):
        src_pid = _mk_project("copySrcAttrs")
        dst_pid = _mk_project("copyDstAttrs")
        src_img = _mk_image(src_pid, "src1.jpg")
        _mk_annotation(src_img, x=0.1, y=0.1, behavior="eat",   animal_id=101)
        _mk_annotation(src_img, x=0.3, y=0.3, behavior="stand", animal_id=202)

        r = client.post("/api/images/bulk_copy_to_project", json={
            "image_ids": [src_img], "target_project_id": dst_pid,
        })
        assert r.status_code == 200, r.text
        assert r.json()["action"] == "copy"

        dst_imgs = _images_of_project(dst_pid)
        assert len(dst_imgs) == 1
        dst_img_id = dst_imgs[0]["id"]
        dst_anns = _fetch_annotations(dst_img_id)

        assert len(dst_anns) == 2
        by_aid = {a["animal_id"]: a for a in dst_anns}
        assert set(by_aid.keys()) == {101, 202}
        assert by_aid[101]["behavior"] == "eat"
        assert by_aid[202]["behavior"] == "stand"

    def test_keypoints_copied(self):
        src_pid = _mk_project("copySrcKP")
        dst_pid = _mk_project("copyDstKP")
        src_img = _mk_image(src_pid, "src2.jpg")
        a = _mk_annotation(src_img, behavior="walk", animal_id=5)
        _mk_keypoint(a, "nose", 0.15, 0.15, vis=1.0)
        _mk_keypoint(a, "withers", 0.20, 0.18, vis=0.9)

        r = client.post("/api/images/bulk_copy_to_project", json={
            "image_ids": [src_img], "target_project_id": dst_pid,
        })
        assert r.status_code == 200, r.text

        dst_imgs = _images_of_project(dst_pid)
        dst_img_id = dst_imgs[0]["id"]
        kp_map = _fetch_keypoints(dst_img_id)
        assert "0" in kp_map
        by_name = {k["name"]: k for k in kp_map["0"]}
        assert set(by_name.keys()) == {"nose", "withers"}
        assert by_name["nose"]["x"] == 0.15
        assert by_name["withers"]["visibility"] == 0.9

    def test_source_image_untouched_after_copy(self):
        """copy=True не должен изменить/удалить источник."""
        src_pid = _mk_project("copySrcIsolate")
        dst_pid = _mk_project("copyDstIsolate")
        src_img = _mk_image(src_pid, "src3.jpg")
        _mk_annotation(src_img, behavior="eat", animal_id=99)

        client.post("/api/images/bulk_copy_to_project", json={
            "image_ids": [src_img], "target_project_id": dst_pid,
        })

        src_anns = _fetch_annotations(src_img)
        assert len(src_anns) == 1
        assert src_anns[0]["behavior"] == "eat"
        assert src_anns[0]["animal_id"] == 99

    def test_copy_uses_distinct_path(self):
        """Целевое изображение должно иметь ДРУГОЙ path — файл реально
        скопирован, а не переиспользован."""
        src_pid = _mk_project("copySrcPath")
        dst_pid = _mk_project("copyDstPath")
        src_img = _mk_image(src_pid, "src4.jpg")
        _mk_annotation(src_img)

        client.post("/api/images/bulk_copy_to_project", json={
            "image_ids": [src_img], "target_project_id": dst_pid,
        })

        db = SessionLocal()
        try:
            src = db.query(ImageModel).filter(ImageModel.id == src_img).first()
            dst_imgs = db.query(ImageModel) \
                         .filter(ImageModel.project_id == dst_pid).all()
            assert len(dst_imgs) == 1
            assert dst_imgs[0].path != src.path
        finally:
            db.close()
