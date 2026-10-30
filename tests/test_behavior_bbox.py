"""[STAGE1-D:test-behavior-bbox] Тесты bbox-relative поведения."""
import pytest
from services.behavior_service import predict_behavior_from_keypoints


def kp(name, x, y, vis=1.0):
    return {"name": name, "x": x, "y": y, "visibility": vis}


class TestBboxRelative:
    def test_drink_works_on_169_frame(self):
        bbox = {"x": 0.1, "y": 0.3, "w": 0.6, "h": 0.6}
        data = [kp("nose", 0.4, 0.84), kp("withers", 0.5, 0.5)]
        r = predict_behavior_from_keypoints(data, bbox=bbox)
        assert r["behavior"] == "drink"
        assert r.get("diag", {}).get("bbox_provided") is True

    def test_drink_works_on_11_frame(self):
        bbox = {"x": 0.2, "y": 0.2, "w": 0.6, "h": 0.6}
        data = [kp("nose", 0.5, 0.75), kp("withers", 0.5, 0.4)]
        r = predict_behavior_from_keypoints(data, bbox=bbox)
        assert r["behavior"] == "drink"

    def test_deprecated_when_no_bbox(self):
        data = [kp("nose", 0.5, 0.9), kp("withers", 0.5, 0.4)]
        r = predict_behavior_from_keypoints(data)
        assert r.get("deprecated") is True
        assert "warning" in r

    def test_bbox_provided_not_deprecated(self):
        bbox = {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}
        data = [kp("nose", 0.3, 0.55), kp("withers", 0.35, 0.3)]
        r = predict_behavior_from_keypoints(data, bbox=bbox)
        assert not r.get("deprecated")

    def test_nose_outside_bbox_not_drink(self):
        bbox = {"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.4}
        data = [kp("nose", 0.3, 0.3), kp("withers", 0.35, 0.25),
                kp("hoof_FL", 0.3, 0.5), kp("hoof_FR", 0.3, 0.5)]
        r = predict_behavior_from_keypoints(data, bbox=bbox)
        assert r["behavior"] != "drink"

    def test_zero_bbox_height_safe(self):
        bbox = {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.0}
        data = [kp("nose", 0.3, 0.5), kp("withers", 0.35, 0.3)]
        r = predict_behavior_from_keypoints(data, bbox=bbox)
        assert r is not None

    def test_empty_keypoints(self):
        r = predict_behavior_from_keypoints([], bbox={"x": 0, "y": 0, "w": 1, "h": 1})
        assert r["behavior"] is None

# [STAGE6:active-regression-test] _check_motion возвращает bbox_moved_ratio
class TestCheckMotionBboxRatio:
    """Проверяет, что _check_motion отдаёт bbox_moved_ratio.

    До Stage 6.21 поле отсутствовало → эвристика 'active' никогда не
    срабатывала в проде (всегда падала в walk или ML-классификатор).
    """

    def test_returns_bbox_moved_ratio(self):
        from datetime import datetime
        from app import (
            _check_motion, SessionLocal,
            Project, ImageModel, Annotation, Video,
        )

        db = SessionLocal()
        try:
            p = Project(
                name="active_ratio_test",
                created_at=datetime.utcnow(), is_deleted=False,
                object_class="pig", object_class_source="list",
            )
            db.add(p); db.commit(); db.refresh(p)

            v = Video(
                project_id=p.id, filename="v.mp4",
                path="/tmp/_nonexist_v.mp4",
                fps=25.0, extract_fps=2.0, is_deleted=False,
            )
            db.add(v); db.commit(); db.refresh(v)

            # Кадр 0: bbox (0.1, 0.1, 0.2, 0.2) → центр (0.2, 0.2)
            im1 = ImageModel(
                project_id=p.id, filename="f0.jpg",
                path="/tmp/_nonexist_f0.jpg",
                width=640, height=640, is_deleted=False,
                video_id=v.id, frame_index=0,
            )
            db.add(im1); db.commit(); db.refresh(im1)
            db.add(Annotation(
                image_id=im1.id, x=0.1, y=0.1, w=0.2, h=0.2,
                label="pig", animal_id=1,
            ))
            db.commit()

            # Кадр 2: bbox (0.4, 0.4, 0.2, 0.2) → центр (0.5, 0.5)
            im2 = ImageModel(
                project_id=p.id, filename="f2.jpg",
                path="/tmp/_nonexist_f2.jpg",
                width=640, height=640, is_deleted=False,
                video_id=v.id, frame_index=2,
            )
            db.add(im2); db.commit(); db.refresh(im2)
            db.add(Annotation(
                image_id=im2.id, x=0.4, y=0.4, w=0.2, h=0.2,
                label="pig", animal_id=1,
            ))
            db.commit()

            motion = _check_motion(db, im2.id, 1)
            assert motion is not None, "_check_motion вернул None"
            assert "bbox_moved_ratio" in motion, (
                f"bbox_moved_ratio отсутствует; keys: {sorted(motion.keys())}"
            )
            # delta = sqrt(0.3² + 0.3²) ≈ 0.424
            # bbox max(w,h) = 0.2
            # ratio ≈ 2.12 — гораздо выше порога 0.20
            assert motion["bbox_moved_ratio"] > 1.0, motion["bbox_moved_ratio"]
            assert motion["frame_gap"] == 2
            assert motion["delta"] > 0.3

            # Cleanup
            db.query(Annotation).filter(
                Annotation.image_id.in_([im1.id, im2.id])
            ).delete(synchronize_session=False)
            db.query(ImageModel).filter(
                ImageModel.id.in_([im1.id, im2.id])
            ).delete(synchronize_session=False)
            db.query(Video).filter(Video.id == v.id).delete(synchronize_session=False)
            db.query(Project).filter(Project.id == p.id).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
