"""[STAGE6-T7] _purge_projects удаляет всё чисто."""
from datetime import datetime

from app import (
    SessionLocal, Project, ImageModel, Annotation, Keypoint, Tag, ImageTag,
)
from services.project_service import _purge_projects


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


def _mk_image(pid, filename):
    db = SessionLocal()
    try:
        im = ImageModel(project_id=pid, filename=filename,
                        path="/tmp/_nonexistent_" + filename,
                        width=640, height=640, is_deleted=False)
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


class TestPurgeProjectsFull:
    def test_purge_removes_all_related_rows(self):
        pid = _mk_project("t7_full")
        iid = _mk_image(pid, "a.jpg")

        db = SessionLocal()
        try:
            a = Annotation(image_id=iid, x=0.1, y=0.1, w=0.2, h=0.2, label="pig")
            db.add(a); db.commit(); db.refresh(a)
            aid = a.id
            db.add(Keypoint(annotation_id=aid, name="nose",
                            x=0.15, y=0.15, visibility=1.0))
            t = Tag(project_id=pid, name="tag1", color="#0071e3")
            db.add(t); db.commit(); db.refresh(t)
            db.add(ImageTag(image_id=iid, tag_id=t.id))
            db.commit()
        finally:
            db.close()

        db = SessionLocal()
        try:
            assert db.query(ImageModel).filter(ImageModel.project_id == pid).count() == 1
            assert db.query(Annotation).filter(Annotation.image_id == iid).count() == 1
            assert db.query(Keypoint).filter(Keypoint.annotation_id == aid).count() == 1

            _purge_projects(db, [pid])

            assert db.query(Project).filter(Project.id == pid).count() == 0
            assert db.query(ImageModel).filter(ImageModel.project_id == pid).count() == 0
            assert db.query(Annotation).filter(Annotation.image_id == iid).count() == 0
            assert db.query(Keypoint).filter(Keypoint.annotation_id == aid).count() == 0
            assert db.query(Tag).filter(Tag.project_id == pid).count() == 0
        finally:
            db.close()
