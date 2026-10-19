"""Юнит-тесты утилит app.py: _norm_behavior, _iou_xywh, _hex_to_int."""
from __future__ import annotations
import pytest

from app import _norm_behavior, _iou_xywh, _hex_to_int, BEHAVIORS


# ---------------------------------------------------------------------------
# _norm_behavior
# ---------------------------------------------------------------------------
class TestNormBehavior:
    def test_all_valid_passthrough(self):
        for b in BEHAVIORS:
            assert _norm_behavior(b) == b

    def test_upper_and_whitespace(self):
        assert _norm_behavior("EAT") == "eat"
        assert _norm_behavior("  Walk  ") == "walk"
        assert _norm_behavior("\tLie\n") == "lie"

    def test_invalid_returns_none(self):
        for bad in ["flying", "eat2", "eat walking", "", " ", "123", "eat_walk"]:
            assert _norm_behavior(bad) is None, "expected None for %r" % bad

    def test_none_returns_none(self):
        assert _norm_behavior(None) is None

    def test_coerces_non_str(self):
        assert _norm_behavior(123) is None
        assert _norm_behavior(True) is None


# ---------------------------------------------------------------------------
# _iou_xywh
# ---------------------------------------------------------------------------
class TestIoU:
    def test_perfect_overlap(self):
        a = {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3}
        assert _iou_xywh(a, a) == pytest.approx(1.0)

    def test_no_overlap(self):
        a = {"x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1}
        b = {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1}
        assert _iou_xywh(a, b) == 0.0

    def test_partial_overlap(self):
        a = {"x": 0.0, "y": 0.0, "w": 0.2, "h": 0.2}
        b = {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}
        assert _iou_xywh(a, b) == pytest.approx(0.01 / 0.07)

    def test_b_is_inside_a(self):
        a = {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}
        b = {"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}
        assert _iou_xywh(a, b) == pytest.approx(0.04)

    def test_symmetric(self):
        a = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
        b = {"x": 0.2, "y": 0.1, "w": 0.4, "h": 0.3}
        assert _iou_xywh(a, b) == pytest.approx(_iou_xywh(b, a))

    def test_zero_area_returns_zero(self):
        a = {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
        b = {"x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1}
        assert _iou_xywh(a, b) == 0.0

    def test_touching_edges_no_overlap(self):
        a = {"x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1}
        b = {"x": 0.1, "y": 0.0, "w": 0.1, "h": 0.1}
        assert _iou_xywh(a, b) == 0.0


# ---------------------------------------------------------------------------
# _hex_to_int
# ---------------------------------------------------------------------------
class TestHexToInt:
    def test_zero(self):
        assert _hex_to_int("0000000000000000") == 0

    def test_max_uint64(self):
        assert _hex_to_int("ffffffffffffffff") == 2**64 - 1

    def test_small_values(self):
        assert _hex_to_int("0000000000000001") == 1
        assert _hex_to_int("000000000000000f") == 15
        assert _hex_to_int("0000000000000010") == 16

    def test_case_insensitive(self):
        assert _hex_to_int("abcdef0000000000") == _hex_to_int("ABCDEF0000000000")

    def test_none_and_empty(self):
        assert _hex_to_int(None) == -1
        assert _hex_to_int("") == -1

    def test_wrong_length(self):
        assert _hex_to_int("abcd") == -1
        assert _hex_to_int("00000000000000000") == -1

    def test_invalid_chars(self):
        assert _hex_to_int("zzzzzzzzzzzzzzzz") == -1
        assert _hex_to_int("000000000000 000") == -1

    def test_expected_len_none_skips_length_check(self):
        assert _hex_to_int("abcd", expected_len=None) == 0xabcd
