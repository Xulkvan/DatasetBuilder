"""[STAGE6-T1] Orphan keypoints при purge проекта.

Проверяет, что _purge_projects удаляет не только Annotation, но и
связанные Keypoint (без FK-каскада, т.к. bulk-delete его не вызывает).
"""
from datetime import datetime

from app import (
    SessionLocal, Project, ImageModel, Annotation, Keypoint,
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


def _mk_ann(iid, **kw):
    db = SessionLocal()
    try:
        a = Annotation(image_id=iid,
                       x=kw.get("x", 0.1), y=kw.get("y", 0.1),
                       w=kw.get("w", 0.2), h=kw.get("h", 0.2),
                       label="pig", confidence=kw.get("confidence"),
                       is_frozen=False,
                       behavior=kw.get("behavior"),
                       animal_id=kw.get("animal_id"))
        db.add(a); db.commit(); db.refresh(a)
        return a.id
    finally:
        db.close()


def _mk_kp(aid, name="nose", x=0.5, y=0.5, vis=1.0):
    db = SessionLocal()
    try:
        kp = Keypoint(annotation_id=aid, name=name, x=x, y=y, visibility=vis)
        db.add(kp); db.commit(); db.refresh(kp)
        return kp.id
    finally:
        db.close()


class TestPurgeOrphanKeypoints:
    def test_purge_removes_keypoints(self):
        pid = _mk_project("t1_purge")
        iid = _mk_image(pid)
        a1 = _mk_ann(iid)
        a2 = _mk_ann(iid)
        _mk_kp(a1, "nose")
        _mk_kp(a1, "withers")
        _mk_kp(a2, "nose")

        db = SessionLocal()
        try:
            kps_before = db.query(Keypoint).filter(
                Keypoint.annotation_id.in_([a1, a2])
            ).count()
            assert kps_before == 3

            _purge_projects(db, [pid])

            kps_after = db.query(Keypoint).filter(
                Keypoint.annotation_id.in_([a1, a2])
            ).count()
            assert kps_after == 0, f"orphan keypoints: {kps_after}"

            anns_after = db.query(Annotation).filter(
                Annotation.id.in_([a1, a2])
            ).count()
            assert anns_after == 0

            proj_after = db.query(Project).filter(Project.id == pid).count()
            assert proj_after == 0
        finally:
            db.close()
