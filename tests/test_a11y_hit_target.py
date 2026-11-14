"""Patcher 6 — A11y hit target (A11Y-03).

Регрессия: icon-only кнопки должны иметь hit-area ≥ 44×44 через
::before { inset: -Npx }.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "style.css"


def test_attr_btn_position_relative():
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.attr-btn\s*\{([^}]*)\}", css)
    assert m, ".attr-btn rule not found"
    body = m.group(1)
    assert "position: relative" in body, \
        ".attr-btn должен иметь position: relative"


def test_attr_btn_before_inset():
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.attr-btn::before\s*\{([^}]*)\}", css)
    assert m, ".attr-btn::before rule not found — Patcher 6 не применён"
    body = m.group(1)
    assert "inset: -8px" in body or "inset:-8px" in body, \
        ".attr-btn::before должен иметь inset: -8px"


def test_icon_btns_have_hit_target():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(r"\.icon-btn::before", css), \
        ".icon-btn::before отсутствует — hit-target расширение потеряно"
