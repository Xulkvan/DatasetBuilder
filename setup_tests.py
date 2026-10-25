#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_tests_v2.py — создаёт tests/test_backup.py и tests/test_bulk_transfer.py.

Закрывают правки:
  #2  backup_project: сохраняет keypoints + behavior + animal_id
  #5  bulk_copy_to_project: сохраняет keypoints + behavior + animal_id

По умолчанию DRY-RUN. Реальное создание — --apply.
Существующие файлы НЕ перезаписываются без --force.

Использование:
    python setup_tests_v2.py                  # dry-run
    python setup_tests_v2.py --apply          # создать
    python setup_tests_v2.py --apply --force  # перезаписать
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


# ===========================================================================
# tests/test_backup.py — правка #2
# ===========================================================================
TEST_BACKUP = '''"""Интеграционные тесты для backup_project (правка #2).

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
'''


# ===========================================================================
# tests/test_bulk_transfer.py — правка #5
# ===========================================================================
TEST_BULK_TRANSFER = '''"""Интеграционные тесты для bulk copy (правка #5).

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
            dst_imgs = db.query(ImageModel) \\
                         .filter(ImageModel.project_id == dst_pid).all()
            assert len(dst_imgs) == 1
            assert dst_imgs[0].path != src.path
        finally:
            db.close()
'''


FILES = {
    "tests/test_backup.py": TEST_BACKUP,
    "tests/test_bulk_transfer.py": TEST_BULK_TRANSFER,
}


def _plan(force: bool):
    out = []
    for rel, content in FILES.items():
        p = ROOT / rel
        if not p.exists():
            out.append((rel, "new", content))
        elif force:
            out.append((rel, "overwrite", content))
        else:
            out.append((rel, "exists", None))
    return out


def _apply(force: bool, dry: bool) -> int:
    plan = _plan(force)
    print("=" * 72)
    print("ПЛАН (setup_tests_v2)")
    print("=" * 72)
    n_new = n_exist = n_over = 0
    for rel, st, _c in plan:
        mark = {"new": "+", "exists": "=", "overwrite": "~"}[st]
        print("  [%s] %s" % (mark, rel))
        if st == "new":
            n_new += 1
        elif st == "exists":
            n_exist += 1
        else:
            n_over += 1

    print()
    print("Новых: %d, пропущено (уже есть): %d, перезапись: %d"
          % (n_new, n_exist, n_over))

    if dry:
        print("\n[DRY-RUN] Ничего не создано. Запусти с --apply.")
        if n_exist and not force:
            print("         Существующие файлы НЕ перезаписываются "
                  "(используй --force).")
        return 0

    created = skipped = 0
    for rel, st, content in plan:
        if st == "exists":
            skipped += 1
            continue
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print("  %s %s" % ("~" if st == "overwrite" else "+", rel))
        created += 1

    print()
    print("Готово. Создано/перезаписано: %d, пропущено: %d"
          % (created, skipped))
    print()
    print("Дальше:")
    print("  pytest tests/test_backup.py tests/test_bulk_transfer.py -v")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Создаёт tests/test_backup.py и tests/test_bulk_transfer.py.")
    ap.add_argument("--apply", action="store_true", help="реально создать файлы")
    ap.add_argument("--force", action="store_true",
                    help="перезаписать существующие файлы")
    args = ap.parse_args()
    return _apply(force=args.force, dry=not args.apply)


if __name__ == "__main__":
    sys.exit(main())