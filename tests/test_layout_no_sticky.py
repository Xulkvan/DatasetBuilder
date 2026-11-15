"""Stage 4: attr-bar/hint/tag-chips-bar не sticky; .main — flex-column.

Регрессия: sticky bottom на .attr-bar перекрывает холст на маленьких
экранах. После Stage 4 attr-bar, hint, tag-chips-bar — обычные блоки
в flex-column потоке .main; общий скролл — через .main { overflow-y: auto }.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "style.css"


def _block(css: str, selector: str) -> str:
    """Return body of a top-level CSS rule (selector starts at line begin)."""
    pat = re.compile(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}")
    m = pat.search(css)
    assert m, f"{selector} rule not found in style.css"
    return m.group(1)


def test_attr_bar_not_sticky():
    css = CSS.read_text(encoding="utf-8")
    body = _block(css, ".attr-bar")
    assert "position: sticky" not in body, (
        ".attr-bar всё ещё position: sticky — Stage 4 не применён"
    )
    assert "position: static" in body, ".attr-bar должен быть position: static"
    assert "bottom: auto" in body, ".attr-bar должен иметь bottom: auto"
    assert "margin-top: var(--sp-4)" in body, (
        ".attr-bar должен иметь margin-top: var(--sp-4)"
    )


def test_hint_not_sticky():
    css = CSS.read_text(encoding="utf-8")
    body = _block(css, ".hint")
    assert "position: sticky" not in body, (
        ".hint sticky — Stage 4 не применён"
    )


def test_tag_chips_bar_not_sticky():
    css = CSS.read_text(encoding="utf-8")
    body = _block(css, ".tag-chips-bar")
    assert "position: sticky" not in body, (
        ".tag-chips-bar sticky — Stage 4 не применён"
    )


def test_main_is_flex_column():
    css = CSS.read_text(encoding="utf-8")
    body = _block(css, ".main")
    assert "display: flex" in body, ".main должен быть display: flex"
    assert "flex-direction: column" in body, (
        ".main должен быть flex-direction: column"
    )
    assert "overflow-y: auto" in body, ".main должен иметь overflow-y: auto"
    assert "grid-template-rows" not in body, (
        ".main всё ещё использует grid-template-rows — Stage 4 не применён"
    )


def test_canvas_host_flex_grow():
    css = CSS.read_text(encoding="utf-8")
    body = _block(css, "#canvasHost")
    assert "flex: 1 0 auto" in body, "#canvasHost должен иметь flex: 1 0 auto"
    assert "min-height: 400px" in body, "#canvasHost должен иметь min-height: 400px"
    assert "overflow: visible" in body, "#canvasHost должен иметь overflow: visible"
    assert "overflow: hidden" not in body, (
        "#canvasHost всё ещё overflow: hidden — Stage 4 не применён"
    )


def test_no_grid_row_overrides():
    css = CSS.read_text(encoding="utf-8")
    for sel in (".main > .active-learning-banner",
                ".main > .tag-chips-bar",
                ".main > .hint"):
        pat = re.compile(re.escape(sel) + r"\s*\{[^}]*grid-row")
        assert not pat.search(css), (
            f"grid-row override для {sel} всё ещё в style.css"
        )


def test_focus_mode_canvas_no_margin_auto():
    css = CSS.read_text(encoding="utf-8")
    m = re.search(
        r'html\[data-focus-mode="1"\] #canvasHost\s*\{([^}]*)\}',
        css,
    )
    assert m, 'html[data-focus-mode="1"] #canvasHost rule not found'
    assert "margin: auto 0" not in m.group(1), (
        "focus-mode #canvasHost всё ещё margin: auto 0 — "
        "Stage 4 не применён (конфликтует с flex: 1 0 auto)"
    )


def test_no_inline_sticky_in_index():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for elem_id in ("attrBar", "hintBlock", "tagChipsBar"):
        pat = re.compile(
            r'id="' + elem_id + r'"[^>]*style="[^"]*position:\s*sticky',
            re.IGNORECASE,
        )
        assert not pat.search(html), (
            f"inline position: sticky on #{elem_id} — Stage 4 не применён"
        )


def test_main_height_is_100_percent():
    """Уточнение 3: .main { height: 100% } вместо 100vh/100dvh.

    100% наследует resolved-высоту .app (который сам 100dvh) без
    дублирования dvh-логики и без mobile-browser-chrome-багов.
    """
    css = CSS.read_text(encoding="utf-8")
    body = _block(css, ".main")
    assert "height: 100%" in body, ".main должен иметь height: 100%"
    assert "height: 100vh" not in body, ".main не должен использовать 100vh"
    assert "height: 100dvh" not in body, ".main не должен использовать 100dvh"
    assert "min-height: 0" in body, ".main должен иметь min-height: 0"


def test_attr_bar_radius_not_flat():
    """Отклонение подтверждено: border-radius = полное скругление.

    Плоские нижние углы (var(--radius-window) 0 0) — остаток sticky-панели,
    после снятия sticky выглядят как баг (карточка «склеена с полом»).
    """
    css = CSS.read_text(encoding="utf-8")
    body = _block(css, ".attr-bar")
    assert "border-radius: var(--radius-window)" in body, (
        ".attr-bar должен иметь полное скругление border-radius: var(--radius-window)"
    )
    assert "var(--radius-window) 0 0" not in body, (
        ".attr-bar: плоские нижние углы (… var(--radius-window) 0 0) запрещены"
    )


def test_toolbar_still_sticky():
    """Уточнение 2: .toolbar остаётся position: sticky; top: 0.

    Уточнение 1: grid-row должен быть удалён из блока .toolbar.
    """
    css = CSS.read_text(encoding="utf-8")
    body = _block(css, ".toolbar")
    assert "position: sticky" in body, (
        ".toolbar должен остаться position: sticky (Уточнение 2)"
    )
    assert "top: 0" in body, ".toolbar должен иметь top: 0"
    assert "grid-row" not in body, (
        ".toolbar: grid-row должен быть удалён (Уточнение 1)"
    )


def test_status_bar_still_sticky():
    """Уточнение 2: .status-bar остаётся position: sticky.

    Уточнение 1: grid-row должен быть удалён из блока .status-bar.
    """
    css = CSS.read_text(encoding="utf-8")
    body = _block(css, ".status-bar")
    assert "position: sticky" in body, (
        ".status-bar должен остаться position: sticky (Уточнение 2)"
    )
    assert "grid-row" not in body, (
        ".status-bar: grid-row должен быть удалён (Уточнение 1)"
    )


def test_no_grid_row_in_individual_blocks():
    """Уточнение 1: grid-row не должно быть ни в одном из этих блоков."""
    css = CSS.read_text(encoding="utf-8")
    for sel in (".toolbar", ".status-bar", "#canvasHost", ".attr-bar"):
        body = _block(css, sel)
        assert "grid-row" not in body, (
            f"{sel}: grid-row должен быть удалён (Stage 4, Уточнение 1)"
        )
