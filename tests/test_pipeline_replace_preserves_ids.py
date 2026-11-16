"""Replace-режим сохраняет Annotation.id и защищает frozen-рамки."""
from datetime import datetime


def _mk_project(db, name="P"):
    from models import Project
    p = Project(name=name, created_at=datetime.utcnow(),
                is_deleted=False, object_class="pig",
                object_class_source="list")
    db.add(p); db.commit(); db.refresh(p)
    return p.id


def _mk_image(db, pid, name="a.jpg"):
    from models import ImageModel
    im = ImageModel(project_id=pid, filename=name, path="/tmp/_r_" + name,
                    width=640, height=640, is_deleted=False,
                    created_at=datetime.utcnow())
    db.add(im); db.commit(); db.refresh(im)
    return im.id


def _mk_ann(db, iid, x=0.1, y=0.1, w=0.2, h=0.2, frozen=False,
            behavior=None, animal_id=None):
    from models import Annotation
    a = Annotation(image_id=iid, x=x, y=y, w=w, h=h, label="pig",
                   confidence=None, is_frozen=frozen,
                   behavior=behavior, animal_id=animal_id)
    db.add(a); db.commit(); db.refresh(a)
    return a.id


def _box(x=0.1, y=0.1, w=0.2, h=0.2, conf=0.9):
    return {"x": x, "y": y, "w": w, "h": h,
            "label": "pig", "confidence": conf}


def test_replace_preserves_ids_and_metadata(local_app_client):
    from app import SessionLocal
    from services.ml_service import _save_autolabel_no_commit

    db = SessionLocal()
    try:
        pid = _mk_project(db)
        iid = _mk_image(db, pid)
        keep = _mk_ann(db, iid, x=0.1, y=0.1, w=0.2, h=0.2,
                       behavior="eat", animal_id=7)
        gone = _mk_ann(db, iid, x=0.7, y=0.7, w=0.2, h=0.2)

        res = _save_autolabel_no_commit(
            db, iid, [_box(x=0.11, y=0.11, w=0.2, h=0.2), _box(x=0.5, y=0.5)],
            "pig")
        db.commit()

        from models import Annotation
        rows = db.query(Annotation).filter(Annotation.image_id == iid).all()
        by_id = {a.id: a for a in rows}
        assert keep in by_id, "совпавшая рамка должна сохранить id"
        assert by_id[keep].behavior == "eat"
        assert by_id[keep].animal_id == 7
        assert gone not in by_id
        assert res["updated"] == 1
        assert res["added"] == 1
        assert res["removed"] == 1
    finally:
        db.close()


def test_replace_keeps_frozen_unless_forced(local_app_client):
    from app import SessionLocal
    from services.ml_service import _save_autolabel_no_commit

    db = SessionLocal()
    try:
        pid = _mk_project(db, "P2")
        iid = _mk_image(db, pid)
        frozen = _mk_ann(db, iid, x=0.1, y=0.1, w=0.2, h=0.2, frozen=True)

        res = _save_autolabel_no_commit(db, iid, [_box(x=0.1, y=0.1)], "pig")
        db.commit()
        from models import Annotation
        a = db.query(Annotation).filter(Annotation.id == frozen).first()
        assert a is not None and a.is_frozen
        assert res["skipped_frozen"] == 1
        assert res["added"] == 0

        res2 = _save_autolabel_no_commit(
            db, iid, [_box(x=0.1, y=0.1)], "pig",
            force_replace_frozen=True)
        db.commit()
        db.refresh(a)
        assert a.id == frozen
        assert res2["skipped_frozen"] == 0
    finally:
        db.close()
