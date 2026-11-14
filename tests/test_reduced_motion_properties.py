"""Patcher 4 — reduced-motion whitelist for loading indicators.

Загрузочные индикаторы (.status-spinner, .migrate-spinner, .skeleton::after,
.save-indicator.dirty) должны продолжать анимироваться под
`prefers-reduced-motion: reduce`.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = ROOT / "style.css"


def _extract_reduced_motion_block(css: str) -> str:
    """Найти @media (prefers-reduced-motion: reduce), содержащий глобальный
    селектор `*` (с `animation-duration: 0.001ms`). В style.css есть
    ДВА таких блока: маленький (training-pulse) и основной (с `*`)."""
    marker = "@media (prefers-reduced-motion: reduce)"
    start = 0
    while True:
        idx = css.find(marker, start)
        assert idx >= 0, (
            "prefers-reduced-motion block not found in style.css"
        )
        depth = 0
        end = idx
        for i in range(idx, len(css)):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = css[idx:end + 1]
        if "animation-duration: 0.001ms !important" in body:
            return body
        start = end + 1
    raise AssertionError(
        "prefers-reduced-motion block с 'animation-duration: 0.001ms' "
        "не найден в style.css"
    )


def test_reduced_motion_has_whitelist():
    css = CSS_PATH.read_text(encoding="utf-8")
    block = _extract_reduced_motion_block(css)
    for sel in (".status-spinner", ".migrate-spinner",
                ".skeleton::after", ".save-indicator.dirty"):
        assert sel in block, f"{sel} missing from reduced-motion whitelist"
    assert "animation-duration: inherit" in block, (
        "whitelist must set `animation-duration: inherit !important`"
    )


def test_reduced_motion_still_blocks_decorative():
    css = CSS_PATH.read_text(encoding="utf-8")
    block = _extract_reduced_motion_block(css)
    # глобальный блок
    assert "animation-duration: 0.001ms !important" in block


def test_view_transitions_disabled_in_reduced_motion():
    css = CSS_PATH.read_text(encoding="utf-8")
    block = _extract_reduced_motion_block(css)
    assert "::view-transition-group(*)" in block
    assert "::view-transition-new(*)" in block
