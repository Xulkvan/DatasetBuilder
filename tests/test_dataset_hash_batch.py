"""[STAGE6-T9] calculate_dataset_hash не падает на большом наборе."""
from datetime import datetime

from app import (
    SessionLocal, Project, ImageModel, Annotation, Keypoint,
)
from services.versioning_service import calculate_dataset_hash


def test_hash_deterministic():
    db = SessionLocal()
    try:
        p = Project(name="t9_hash", created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        pid = p.id

        for k in range(5):
            im = ImageModel(project_id=pid, filename=f"img_{k}.jpg",
                            path=f"/tmp/_nonexistent_{k}.jpg",
                            width=640, height=640, is_deleted=False)
            db.add(im); db.commit(); db.refresh(im)
            a = Annotation(image_id=im.id, x=0.1, y=0.1, w=0.2, h=0.2,
                           label="pig", behavior="eat", animal_id=k + 1)
            db.add(a); db.commit(); db.refresh(a)
            db.add(Keypoint(annotation_id=a.id, name="nose",
                            x=0.15, y=0.15, visibility=1.0))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        h1 = calculate_dataset_hash(db, pid)
        h2 = calculate_dataset_hash(db, pid)
        assert h1 == h2, "hash должен быть детерминирован"
        assert len(h1) == 64
        assert all(c in "0123456789abcdef" for c in h1)
    finally:
        db.close()


def test_hash_changes_on_annotation_change():
    db = SessionLocal()
    try:
        p = Project(name="t9_hash2", created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        pid = p.id
        im = ImageModel(project_id=pid, filename="x.jpg",
                        path="/tmp/_nonexistent_x.jpg",
                        width=640, height=640, is_deleted=False)
        db.add(im); db.commit(); db.refresh(im)
        a = Annotation(image_id=im.id, x=0.1, y=0.1, w=0.2, h=0.2, label="pig")
        db.add(a); db.commit(); db.refresh(a)
        aid = a.id
    finally:
        db.close()

    db = SessionLocal()
    try:
        h_before = calculate_dataset_hash(db, pid)
        db.query(Annotation).filter(Annotation.id == aid).update(
            {"x": 0.99}, synchronize_session=False)
        db.commit()
        h_after = calculate_dataset_hash(db, pid)
        assert h_before != h_after, "hash должен меняться при смене разметки"
    finally:
        db.close()


def test_hash_does_not_load_all_into_memory():
    """[STAGE6] Hash на 200 изображениях выполняется и совпадает при повторе.

    Регрессия: раньше calculate_dataset_hash делал .all() и загружал
    все ImageModel объекты в память. Для 50k+ изображений это OOM.
    После STAGE6_PERF_MEMORY используется yield_per(1000).
    """
    db = SessionLocal()
    try:
        p = Project(
            name="stage6_hash_mem",
            created_at=datetime.utcnow(),
            is_deleted=False,
            object_class="pig",
            object_class_source="list",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        pid = p.id
        for k in range(200):
            im = ImageModel(
                project_id=pid,
                filename=f"hash_{k:04d}.jpg",
                path=f"/tmp/_stage6_hash_nonexistent_{k}.jpg",
                width=640, height=640, is_deleted=False,
            )
            db.add(im)
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        h1 = calculate_dataset_hash(db, pid)
        h2 = calculate_dataset_hash(db, pid)
        assert h1 == h2, "hash должен быть детерминирован"
        assert len(h1) == 64
    finally:
        db.close()


def test_hash_uses_yield_per():
    """[STAGE6] Regression: hash использует yield_per, а не .all()."""
    import inspect
    from services import versioning_service
    src = inspect.getsource(versioning_service.calculate_dataset_hash)
    assert "yield_per(1000)" in src, (
        "calculate_dataset_hash не использует yield_per(1000) — "
        "STAGE6_PERF_MEMORY не применён"
    )
    assert "images = (db.query(ImageModel)" not in src, (
        "calculate_dataset_hash всё ещё грузит .all() ImageModel в память"
    )
