"""[PATCH:STAGE5-T5-fix] C27: _purge_projects удаляет все FK-зависимости.

Fix: Webhook, DatasetVersion, Stream, ProjectKeypointSchema,
BehaviorValidation, User, UserProjectAccess импортируются из models
(в app.py они НЕ ре-экспортируются).
"""
import uuid
from datetime import datetime

# То, что app.py реально ре-экспортирует:
from app import (
    SessionLocal, Project, ImageModel, Annotation, Keypoint,
)
# Всё остальное — только из models:
from models import (
    Webhook, DatasetVersion, Stream, ProjectKeypointSchema,
    BehaviorValidation, User,
)
from services.project_service import _purge_projects

try:
    from models import UserProjectAccess
except ImportError:
    UserProjectAccess = None


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


def _mk_user():
    db = SessionLocal()
    try:
        u = User(username="t5_" + uuid.uuid4().hex[:8],
                 password_hash="x", role="annotator", is_active=1,
                 created_at=datetime.utcnow())
        db.add(u); db.commit(); db.refresh(u)
        return u.id
    finally:
        db.close()


def _mk_image(pid, filename="a.jpg"):
    db = SessionLocal()
    try:
        im = ImageModel(project_id=pid, filename=filename,
                        path="/tmp/_t5_" + filename,
                        width=640, height=640, is_deleted=False)
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


def _mk_ann(iid):
    db = SessionLocal()
    try:
        a = Annotation(image_id=iid, x=0.1, y=0.1, w=0.2, h=0.2, label="pig")
        db.add(a); db.commit(); db.refresh(a)
        return a.id
    finally:
        db.close()


class TestPurgeFull:
    def test_purge_removes_all_related_rows(self):
        pid = _mk_project("t5_full")
        iid = _mk_image(pid, "a.jpg")
        aid = _mk_ann(iid)
        uid = _mk_user()

        db = SessionLocal()
        try:
            db.add(Keypoint(annotation_id=aid, name="nose",
                            x=0.15, y=0.15, visibility=1.0))
            db.add(Webhook(project_id=pid, url="http://x.test/h",
                           event_type="annotation.saved",
                           secret_key="", active=True,
                           created_at=datetime.utcnow()))
            db.add(DatasetVersion(project_id=pid, hash="a" * 32,
                                  created_at=datetime.utcnow(),
                                  image_count=1, annotation_count=1))
            db.add(Stream(project_id=pid, url="rtsp://x", name="s",
                          is_active=False))
            db.add(ProjectKeypointSchema(project_id=pid,
                                         schema_json='[{"name":"nose"}]'))
            db.add(BehaviorValidation(
                annotation_id=aid, project_id=pid,
                auto_behavior="eat", true_behavior="eat", is_match=1,
                validated_at=datetime.utcnow(),
            ))
            if UserProjectAccess is not None:
                db.add(UserProjectAccess(user_id=uid, project_id=pid))
            db.commit()
        finally:
            db.close()

        db = SessionLocal()
        try:
            _purge_projects(db, [pid])

            assert db.query(Project).filter(Project.id == pid).count() == 0
            assert db.query(ImageModel).filter(
                ImageModel.project_id == pid).count() == 0
            assert db.query(Annotation).filter(
                Annotation.image_id == iid).count() == 0
            assert db.query(Keypoint).filter(
                Keypoint.annotation_id == aid).count() == 0
            assert db.query(Webhook).filter(
                Webhook.project_id == pid).count() == 0
            assert db.query(DatasetVersion).filter(
                DatasetVersion.project_id == pid).count() == 0
            assert db.query(Stream).filter(
                Stream.project_id == pid).count() == 0
            assert db.query(ProjectKeypointSchema).filter(
                ProjectKeypointSchema.project_id == pid).count() == 0
            assert db.query(BehaviorValidation).filter(
                BehaviorValidation.project_id == pid).count() == 0
            if UserProjectAccess is not None:
                assert db.query(UserProjectAccess).filter(
                    UserProjectAccess.project_id == pid).count() == 0
        finally:
            db.close()

    def test_purge_with_webhook_and_version(self):
        pid = _mk_project("t5_wh_ver")
        db = SessionLocal()
        try:
            db.add(Webhook(project_id=pid, url="http://x.test/h",
                           event_type="annotation.saved",
                           secret_key="", active=True,
                           created_at=datetime.utcnow()))
            db.add(DatasetVersion(project_id=pid, hash="b" * 32,
                                  created_at=datetime.utcnow(),
                                  image_count=0, annotation_count=0))
            db.commit()
        finally:
            db.close()
        db = SessionLocal()
        try:
            _purge_projects(db, [pid])
            assert db.query(Webhook).filter(
                Webhook.project_id == pid).count() == 0
            assert db.query(DatasetVersion).filter(
                DatasetVersion.project_id == pid).count() == 0
        finally:
            db.close()
