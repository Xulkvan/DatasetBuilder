"""Patcher 2 — toolbar full-width (GG-01) + .main grid layout."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "style.css"


def _top_level_rule_body(css: str, selector: str) -> str:
    """Возвращает тело top-level CSS-правила `selector { ... }`."""
    pattern = re.compile(
        rf"(?:^|\n)\s*{re.escape(selector)}\s*\{{([^}}]*)\}}",
        re.MULTILINE,
    )
    m = pattern.search(css)
    assert m, f"{selector} top-level rule not found in style.css"
    return m.group(1)


def test_toolbar_full_width():
    """GG-01: .toolbar — display:flex, width:100%, no inline-flex/fit-content."""
    body = _top_level_rule_body(CSS.read_text(encoding="utf-8"), ".toolbar")
    assert "display: inline-flex" not in body, (
        ".toolbar всё ещё display: inline-flex — GG-01 не применён"
    )
    assert "width: fit-content" not in body, (
        ".toolbar всё ещё width: fit-content — GG-01 не применён"
    )
    assert "display: flex" in body
    assert "width: 100%" in body


def test_main_uses_grid():
    """.main — display: grid с 1fr для #canvasHost."""
    body = _top_level_rule_body(CSS.read_text(encoding="utf-8"), ".main")
    assert "display: grid" in body, (
        ".main должен быть display: grid — иначе toolbar/attr-bar sticky не работает"
    )
    assert "grid-template-rows" in body
    assert "1fr" in body, "1fr row (#canvasHost) отсутствует"


def test_attr_bar_sticky_bottom():
    """F-10: attr-bar прибит к низу окна."""
    body = _top_level_rule_body(CSS.read_text(encoding="utf-8"), ".attr-bar")
    assert "position: sticky" in body, ".attr-bar должен быть position: sticky"
    assert "bottom: 0" in body, ".attr-bar должен иметь bottom: 0"


def test_canvas_host_flex_center():
    """#canvasHost — flex center + min-height:0."""
    body = _top_level_rule_body(CSS.read_text(encoding="utf-8"), "#canvasHost")
    assert "min-height: 0" in body
    assert "display: flex" in body
    assert "align-items: center" in body
    assert "justify-content: center" in body


def test_toolbar_no_margin_bottom():
    """Toolbar больше не floating — margin-bottom убран (grid gap 0)."""
    body = _top_level_rule_body(CSS.read_text(encoding="utf-8"), ".toolbar")
    assert "margin-bottom" not in body, (
        ".toolbar должен быть прибит к окну — margin-bottom запрещён"
    )
