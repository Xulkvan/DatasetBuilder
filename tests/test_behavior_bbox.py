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
