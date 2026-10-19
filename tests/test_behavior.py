"""Тесты predict_behavior_from_keypoints."""
from __future__ import annotations
import pytest

from app import (
    predict_behavior_from_keypoints,
    BEHAVIOR_DRINK_NOSE_Y,
    BEHAVIOR_ACTIVE_DELTA,
    BEHAVIOR_WALK_DELTA,
)


def kp(name, x, y, vis=1.0):
    return {"name": name, "x": x, "y": y, "visibility": vis}


def kps(**kv):
    return [kp(n, x, y) for n, (x, y) in kv.items()]


class TestEmptyAndIncomplete:
    def test_empty_returns_no_visible(self):
        r = predict_behavior_from_keypoints([])
        assert r["behavior"] is None
        assert r["reason"] == "no_visible_keypoints"

    def test_none_returns_no_visible(self):
        r = predict_behavior_from_keypoints(None)
        assert r["behavior"] is None
        assert r["reason"] == "no_visible_keypoints"

    def test_only_nose_returns_need_spine(self):
        r = predict_behavior_from_keypoints(kps(nose=(0.5, 0.5)))
        assert r["behavior"] is None
        assert "spine" in r["reason"]

    def test_only_spine_returns_need_nose(self):
        r = predict_behavior_from_keypoints(kps(withers=(0.5, 0.3)))
        assert r["behavior"] is None
        assert "nose" in r["reason"]

    def test_invisible_points_ignored(self):
        data = [
            kp("nose", 0.5, 0.4, vis=0.3),
            kp("withers", 0.5, 0.3, vis=0.3),
        ]
        r = predict_behavior_from_keypoints(data)
        assert r["behavior"] is None
        assert r["reason"] == "no_visible_keypoints"


class TestDrink:
    def test_nose_at_bottom(self):
        data = kps(nose=(0.5, BEHAVIOR_DRINK_NOSE_Y + 0.05),
                   withers=(0.5, 0.4))
        r = predict_behavior_from_keypoints(data)
        assert r["behavior"] == "drink"
        assert r["confidence"] >= 0.7

    def test_nose_just_below_threshold(self):
        data = kps(nose=(0.5, BEHAVIOR_DRINK_NOSE_Y - 0.05),
                   withers=(0.5, 0.4))
        r = predict_behavior_from_keypoints(data)
        assert r["behavior"] != "drink"


class TestEat:
    def test_head_tilt_triggers_eat(self):
        data = kps(
            nose=(0.30, 0.55),
            head_top=(0.35, 0.30),
            withers=(0.50, 0.40),
        )
        r = predict_behavior_from_keypoints(data)
        assert r["behavior"] == "eat"

    def test_no_tilt_no_eat(self):
        data = kps(
            nose=(0.30, 0.30),
            head_top=(0.32, 0.29),
            withers=(0.50, 0.40),
            hoof_FL=(0.5, 0.85),
            hoof_FR=(0.5, 0.85),
        )
        r = predict_behavior_from_keypoints(data)
        assert r["behavior"] != "eat"


class TestLieStand:
    def test_stand_when_hooves_far_below_spine(self):
        data = kps(
            nose=(0.30, 0.30),
            head_top=(0.32, 0.29),
            withers=(0.50, 0.40),
            mid_spine=(0.50, 0.40),
            hip=(0.50, 0.40),
            hoof_FL=(0.5, 0.85),
            hoof_FR=(0.5, 0.85),
        )
        r = predict_behavior_from_keypoints(data)
        assert r["behavior"] == "stand"

    def test_lie_when_hooves_close_to_spine(self):
        data = kps(
            nose=(0.30, 0.30),
            head_top=(0.32, 0.29),
            withers=(0.50, 0.45),
            mid_spine=(0.50, 0.45),
            hip=(0.50, 0.45),
            hoof_FL=(0.5, 0.50),
            hoof_FR=(0.5, 0.50),
        )
        r = predict_behavior_from_keypoints(data)
        assert r["behavior"] == "lie"


class TestMotion:
    def test_active_on_large_delta(self):
        data = kps(nose=(0.5, 0.4), withers=(0.5, 0.4))
        motion = {
            "delta": BEHAVIOR_ACTIVE_DELTA + 0.05,
            "from": [0.5, 0.5],
            "to": [0.65, 0.5],
        }
        r = predict_behavior_from_keypoints(data, motion=motion)
        assert r["behavior"] == "active"

    def test_walk_on_medium_delta(self):
        data = kps(nose=(0.5, 0.4), withers=(0.5, 0.4))
        motion = {
            "delta": (BEHAVIOR_WALK_DELTA + BEHAVIOR_ACTIVE_DELTA) / 2,
            "from": [0.5, 0.5],
            "to": [0.54, 0.5],
        }
        r = predict_behavior_from_keypoints(data, motion=motion)
        assert r["behavior"] == "walk"

    def test_static_when_delta_small(self):
        data = kps(
            nose=(0.3, 0.3), head_top=(0.32, 0.29),
            withers=(0.5, 0.4),
            hoof_FL=(0.5, 0.85), hoof_FR=(0.5, 0.85),
        )
        motion = {"delta": 0.001, "from": [0.5, 0.5], "to": [0.501, 0.5]}
        r = predict_behavior_from_keypoints(data, motion=motion)
        assert r["behavior"] in ("stand", "lie")

    def test_active_beats_drink(self):
        data = kps(nose=(0.5, 0.90), withers=(0.5, 0.4))
        motion = {"delta": 0.20, "from": [0.3, 0.5], "to": [0.5, 0.5]}
        r = predict_behavior_from_keypoints(data, motion=motion)
        assert r["behavior"] == "active"

    def test_drink_beats_walk(self):
        data = kps(nose=(0.5, 0.90), withers=(0.5, 0.4))
        motion = {"delta": 0.03, "from": [0.5, 0.5], "to": [0.53, 0.5]}
        r = predict_behavior_from_keypoints(data, motion=motion)
        assert r["behavior"] == "drink"


class TestResponseShape:
    def test_always_has_required_keys(self):
        r = predict_behavior_from_keypoints([])
        for key in ("behavior", "confidence", "reason"):
            assert key in r

    def test_motion_block_is_passed_through(self):
        data = kps(nose=(0.5, 0.4), withers=(0.5, 0.4))
        motion = {"delta": 0.10, "from": [0.5, 0.5], "to": [0.6, 0.5]}
        r = predict_behavior_from_keypoints(data, motion=motion)
        assert r["motion"] is not None
        assert r["motion"]["delta"] == pytest.approx(0.10)

    def test_diag_present_when_points_valid(self):
        data = kps(
            nose=(0.3, 0.3), head_top=(0.32, 0.29),
            withers=(0.5, 0.4),
            hoof_FL=(0.5, 0.85), hoof_FR=(0.5, 0.85),
        )
        r = predict_behavior_from_keypoints(data)
        assert "diag" in r
        assert "nose_y" in r["diag"]
        assert r["diag"]["nose_y"] == pytest.approx(0.3)
