"""Patcher 5 — blur budget (LG-01/F-06/PERF-01).

Только 5 селекторов имеют право на `backdrop-filter: blur(...)`:
    .toolbar, .modal, .command-palette, .glass,
    .zoom-controls button (floating control поверх холста)
Всё остальное (menus, popovers, tooltips, attr-bar, status, tour, drop-overlay,
контентные баннеры/карточки) — solid tinted (`var(--bg-surface)`), не glass.

Регрессия: `prefers-reduced-transparency: reduce` и
`@supports not (backdrop-filter)` должны покрывать `.glass`.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {".toolbar", ".modal", ".command-palette", ".glass", ".zoom-controls button"}


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _selectors_with_blur(css: str) -> set:
    selectors = set()
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css, re.DOTALL):
        sel = m.group(1).strip()
        body = m.group(2)
        # Только стандартный `backdrop-filter: blur(...)` (не -webkit-).
        if re.search(r"(?:^|[;\s])backdrop-filter\s*:\s*blur\(", body):
            selectors.add(sel)
    return selectors


def test_only_allowed_selectors_have_blur():
    css = _strip_comments((ROOT / "style.css").read_text(encoding="utf-8"))
    offenders = []
    for sel in _selectors_with_blur(css):
        if not any(
            re.search(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", sel)
            for a in ALLOWED
        ):
            offenders.append(sel)
    assert not offenders, (
        f"Blur budget violated. Allowed: {sorted(ALLOWED)}. "
        f"Extra blur-selectors: {offenders}"
    )


def test_glass_tokens_present():
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    for token in (
        "--glass-opacity:", "--glass-blur:", "--glass-saturate:", "--glass-bg:"
    ):
        assert token in css, f"Design token missing: {token}"


def test_glass_utility_class_defined():
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    m = re.search(r"\.glass\s*\{([^}]*)\}", css)
    assert m, ".glass class not defined in style.css"
    body = m.group(1)
    assert "background: var(--glass-bg)" in body
    assert (
        "backdrop-filter: blur(var(--glass-blur)) "
        "saturate(var(--glass-saturate))" in body
    )


def test_modal_specular_after_present():
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.modal::after\s*\{", css), \
        ".modal::after not defined — darkened top gradient missing"
    assert re.search(
        r'\[data-theme="dark"\]\s+\.modal::after\s*\{', css
    ), "[data-theme='dark'] .modal::after not defined"


def test_reduced_transparency_covers_glass():
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    m = re.search(
        r"@media\s*\(prefers-reduced-transparency:\s*reduce\)\s*\{"
        r"([^}]*)\}",
        css, re.DOTALL,
    )
    assert m, "prefers-reduced-transparency block not found"
    assert ".glass" in m.group(1), \
        ".glass missing from prefers-reduced-transparency block"


def test_supports_fallback_covers_glass():
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    idx = css.find("@supports not ((backdrop-filter: blur(1px))")
    assert idx >= 0, "@supports not (backdrop-filter) fallback missing"
    tail = css[idx:idx + 800]
    assert ".glass" in tail, ".glass missing from @supports fallback"


def test_glass_opacity_js_wired():
    js = (ROOT / "js" / "main.js").read_text(encoding="utf-8")
    assert "pdb_glass_opacity" in js, \
        "localStorage key 'pdb_glass_opacity' not used"
    assert "_applyGlassOpacity" in js, \
        "_applyGlassOpacity function missing"
    assert "glassOpacityInput" in js, \
        "glassOpacityInput slider not wired"


def test_i18n_key_present():
    i18n = (ROOT / "i18n.js").read_text(encoding="utf-8")
    assert "'settings.glassOpacity'" in i18n, \
        "i18n key 'settings.glassOpacity' missing"


def test_modal_animating_selector_is_universal():
    """Stage 3: .modal-animating::before покрывает и .modal, и .command-palette."""
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.modal-animating::before\s*\{", css), \
        ".modal-animating::before отсутствует (Stage 3 не применён)"
    assert ".modal.modal-animating::before" not in css, \
        "Stage 2-селектор .modal.modal-animating::before не заменён на универсальный"


def test_command_palette_uses_modal_animation():
    """Stage 3: у .command-palette нет собственного @keyframes."""
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    assert "@keyframes commandPaletteIn" not in css, \
        "Устаревший @keyframes commandPaletteIn не удалён — мигание может вернуться"
    assert "@keyframes command-palette-in" not in css, \
        "Устаревший @keyframes command-palette-in не удалён"

def test_command_palette_uses_modalMaterializeSheet():
    """Stage 3 FIX: palette должна анимироваться через modalMaterializeSheet."""
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    assert re.search(
        r"\.command-palette-dialog[^{]*\.command-palette[^{]*\{[^}]*"
        r"animation:\s*modalMaterializeSheet",
        css, re.DOTALL,
    ), (
        ".command-palette не использует modalMaterializeSheet — "
        "Stage 3.4 не применён или откатился (палитра может "
        "использовать устаревший @keyframes commandPaletteIn → мигание)."
    )
