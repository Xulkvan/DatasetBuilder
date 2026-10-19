"""Интеграционные тесты через FastAPI TestClient.

Защищают правки:
  * #1 get_annotations: order_by(Annotation.id) — согласованность индексов
    с keypoints_by_index и motion_vectors.
  * #3 copy_annotations: сохранять behavior/animal_id + чистить keypoints
    target-а (иначе — IntegrityError или orphan-строки).
  * #4 save_annotations с keypoints: перезапись без UNIQUE constraint failed.

Тесты создают данные напрямую через ORM, чтобы не зависеть от
файловой системы (upload, thumbs) и ML-моделей.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import (
    app, SessionLocal,
    Project, ImageModel, Annotation, Keypoint,
)

# Не используем `with TestClient(...) as c:` — не хотим поднимать
# lifespan-фоновые потоки (bootstrap модели, trash cleaner).
client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _mk_project(name="TestP"):
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


def _mk_annotation(image_id, *, x=0.1, y=0.1, w=0.2, h=0.2,
                   behavior=None, animal_id=None, frozen=False,
                   label="pig", confidence=None):
    db = SessionLocal()
    try:
        a = Annotation(image_id=image_id, x=x, y=y, w=w, h=h,
                       label=label, confidence=confidence,
                       is_frozen=frozen,
                       behavior=behavior, animal_id=animal_id)
        db.add(a); db.commit(); db.refresh(a)
        return a.id
    finally:
        db.close()


def _mk_keypoint(annotation_id, name="nose", x=0.5, y=0.5, vis=1.0):
    db = SessionLocal()
    try:
        kp = Keypoint(annotation_id=annotation_id, name=name,
                      x=x, y=y, visibility=vis)
        db.add(kp); db.commit(); db.refresh(kp)
        return kp.id
    finally:
        db.close()


def _get_annotations_via_api(image_id):
    r = client.get("/api/images/%d/annotations" % image_id)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# #1 — согласованность порядка индексов
# ---------------------------------------------------------------------------
class TestAnnotationOrdering:
    def test_get_annotations_returns_in_id_order(self):
        """Индексы boxes[] на клиенте должны совпадать с индексами, которые
        использует keypoints_by_index и motion_vectors_all.
        Все три места сортируют по Annotation.id."""
        pid = _mk_project("orderP")
        iid = _mk_image(pid)
        a1 = _mk_annotation(iid, x=0.10, y=0.10)
        a2 = _mk_annotation(iid, x=0.30, y=0.30)
        a3 = _mk_annotation(iid, x=0.50, y=0.50)

        anns = _get_annotations_via_api(iid)
        assert len(anns) == 3
        assert [round(a["x"], 2) for a in anns] == [0.10, 0.30, 0.50]

        # keypoints_by_index возвращает словарь {index_str: [...]}, индекс
        # = позиция в этом же порядке.
        r = client.get("/api/images/%d/keypoints_by_index" % iid)
        assert r.status_code == 200, r.text
        rows = r.json()
        # Даже если точек нет — словарь должен содержать ключи "0","1","2"
        # (или быть пустым, если аннотаций нет; у нас они есть).
        assert set(rows.keys()) >= {"0", "1", "2"}


# ---------------------------------------------------------------------------
# #3 — copy_annotations сохраняет behavior/animal_id + чистит keypoints
# ---------------------------------------------------------------------------
class TestCopyAnnotations:
    def test_copy_preserves_behavior_and_animal_id(self):
        pid = _mk_project("copyP")
        src = _mk_image(pid, "src.jpg")
        dst = _mk_image(pid, "dst.jpg")

        _mk_annotation(src, x=0.1, y=0.1, behavior="eat",   animal_id=11)
        _mk_annotation(src, x=0.3, y=0.3, behavior="stand", animal_id=22)

        r = client.post(
            "/api/images/%d/copy_annotations_from/%d" % (dst, src)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 2

        anns = _get_annotations_via_api(dst)
        assert len(anns) == 2
        # Точные значения — источник смысла кнопки "Копировать (N)".
        assert anns[0]["behavior"] == "eat"
        assert anns[0]["animal_id"] == 11
        assert anns[1]["behavior"] == "stand"
        assert anns[1]["animal_id"] == 22

    def test_copy_clears_old_keypoints_of_target(self):
        """У target-а были свои keypoints. После копирования они должны
        исчезнуть (вместе со старыми аннотациями), а не стать orphan'ами."""
        pid = _mk_project("copyKP")
        src = _mk_image(pid, "src.jpg")
        dst = _mk_image(pid, "dst.jpg")

        _mk_annotation(src, x=0.1, y=0.1)

        old_target_ann = _mk_annotation(dst, x=0.9, y=0.9)
        _mk_keypoint(old_target_ann, "nose", 0.9, 0.9)
        _mk_keypoint(old_target_ann, "tail_base", 0.85, 0.95)

        r = client.post(
            "/api/images/%d/copy_annotations_from/%d" % (dst, src)
        )
        assert r.status_code == 200, r.text

        # Проверяем прямо в БД: не осталось ли keypoints от старой аннотации.
        db = SessionLocal()
        try:
            dst_ann_ids = [row.id for row in
                           db.query(Annotation.id)
                             .filter(Annotation.image_id == dst).all()]
            assert len(dst_ann_ids) == 1
            orphan = (db.query(Keypoint)
                        .filter(Keypoint.annotation_id == old_target_ann)
                        .count())
            assert orphan == 0, "old keypoints leaked after copy"
        finally:
            db.close()

    def test_copy_does_not_touch_other_images(self):
        """Копирование A→B не должно затрагивать другие кадры проекта."""
        pid = _mk_project("copyIsolate")
        src = _mk_image(pid, "src.jpg")
        dst = _mk_image(pid, "dst.jpg")
        bystander = _mk_image(pid, "bystander.jpg")

        _mk_annotation(src, x=0.1, y=0.1)
        b_ann = _mk_annotation(bystander, x=0.5, y=0.5, animal_id=99)

        client.post("/api/images/%d/copy_annotations_from/%d" % (dst, src))

        anns = _get_annotations_via_api(bystander)
        assert len(anns) == 1
        assert anns[0]["animal_id"] == 99


# ---------------------------------------------------------------------------
# #4 — save_annotations с keypoints (перезапись без UNIQUE-конфликта)
# ---------------------------------------------------------------------------
class TestSaveAnnotationsWithKeypoints:
    def test_roundtrip_simple(self):
        pid = _mk_project("saveP")
        iid = _mk_image(pid)
        payload = [
            {
                "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2,
                "label": "pig", "confidence": None, "frozen": False,
                "behavior": "walk", "animal_id": 7,
                "keypoints": [
                    {"name": "nose", "x": 0.15, "y": 0.15, "visibility": 1.0},
                    {"name": "withers", "x": 0.18, "y": 0.12, "visibility": 1.0},
                ],
            }
        ]
        r = client.post("/api/images/%d/annotations" % iid, json=payload)
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 1

        anns = _get_annotations_via_api(iid)
        assert len(anns) == 1
        assert anns[0]["behavior"] == "walk"
        assert anns[0]["animal_id"] == 7

        # keypoints_by_index вернёт точки для индекса "0"
        r2 = client.get("/api/images/%d/keypoints_by_index" % iid)
        assert r2.status_code == 200, r2.text
        rows = r2.json()
        assert "0" in rows
        names = [p["name"] for p in rows["0"]]
        assert set(names) == {"nose", "withers"}

    def test_save_twice_replaces_keypoints(self):
        """Вторая отправка с ДРУГИМИ точками не должна падать с
        UNIQUE constraint failed (annotation_id, name) и не должна
        оставлять старых точек."""
        pid = _mk_project("replaceP")
        iid = _mk_image(pid)

        first = [{
            "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2,
            "label": "pig", "confidence": None, "frozen": False,
            "keypoints": [
                {"name": "nose", "x": 0.15, "y": 0.15, "visibility": 1.0},
                {"name": "withers", "x": 0.18, "y": 0.12, "visibility": 1.0},
                {"name": "hip", "x": 0.20, "y": 0.25, "visibility": 1.0},
            ],
        }]
        r1 = client.post("/api/images/%d/annotations" % iid, json=first)
        assert r1.status_code == 200, r1.text

        # Вторая отправка: только 2 точки, другие значения.
        second = [{
            "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2,
            "label": "pig", "confidence": None, "frozen": False,
            "keypoints": [
                {"name": "nose", "x": 0.13, "y": 0.13, "visibility": 1.0},
                {"name": "tail_base", "x": 0.25, "y": 0.27, "visibility": 1.0},
            ],
        }]
        r2 = client.post("/api/images/%d/annotations" % iid, json=second)
        assert r2.status_code == 200, r2.text

        r3 = client.get("/api/images/%d/keypoints_by_index" % iid)
        rows = r3.json()
        names = sorted(p["name"] for p in rows["0"])
        assert names == ["nose", "tail_base"], "old keypoints leaked"

    def test_keypoint_name_validated(self):
        """Невалидное имя точки (не из KEYPOINT_SCHEMA) — пропускается,
        а не падает 500-й."""
        pid = _mk_project("kptValid")
        iid = _mk_image(pid)
        payload = [{
            "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2,
            "label": "pig", "confidence": None, "frozen": False,
            "keypoints": [
                {"name": "nose", "x": 0.15, "y": 0.15, "visibility": 1.0},
                {"name": "unknown_thing", "x": 0.5, "y": 0.5, "visibility": 1.0},
            ],
        }]
        r = client.post("/api/images/%d/annotations" % iid, json=payload)
        assert r.status_code == 200, r.text

        r2 = client.get("/api/images/%d/keypoints_by_index" % iid)
        names = [p["name"] for p in r2.json()["0"]]
        assert names == ["nose"]
