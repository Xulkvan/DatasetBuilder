"""Patcher 3 — WCAG contrast for .box-label (F-02).

Заменяет `background: var(--box-color)` (1.19:1 для --box-mid=#ffcc00) на
solid neutral pill: #f5f5f7 on rgba(28,28,30,0.86) ≈ 15.8:1 (AAA).
"""
import re
from pathlib import Path


def _channel(c: int) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb: tuple) -> float:
    r, g, b = rgb
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def _contrast_ratio(fg: tuple, bg: tuple) -> float:
    L1 = _relative_luminance(fg)
    L2 = _relative_luminance(bg)
    if L1 < L2:
        L1, L2 = L2, L1
    return (L1 + 0.05) / (L2 + 0.05)


def _hex(h: str) -> tuple:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def test_box_label_contrast_light():
    ratio = _contrast_ratio(_hex("f5f5f7"), _hex("1c1c1e"))
    assert ratio >= 7.0, f"light contrast {ratio:.2f} < 7.0 (AAA)"


def test_box_label_contrast_dark():
    ratio = _contrast_ratio(_hex("1d1d1f"), _hex("f5f5f7"))
    assert ratio >= 7.0, f"dark contrast {ratio:.2f} < 7.0 (AAA)"


def test_box_label_no_backdrop_filter():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    for m in re.finditer(r"\.box-label\s*\{([^}]*)\}", css):
        body = m.group(1)
        assert "backdrop-filter" not in body, (
            "backdrop-filter on .box-label — GPU fail (>= 20 labels x blur)"
        )


def test_box_label_is_neutral_solid():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    pattern = re.compile(
        r"\.box-label\s*\{[^}]*background:\s*([^;]+);", re.DOTALL
    )
    m = pattern.search(css)
    assert m, ".box-label background not found"
    val = m.group(1).strip()
    assert "rgba(28, 28, 30" in val or "rgba(28,28,30" in val, (
        f".box-label background must be neutral solid rgba(28,28,30,...), got: {val}"
    )
    assert "var(--box-color" not in val, (
        ".box-label still uses per-confidence color as background — F-02 not fixed"
    )
