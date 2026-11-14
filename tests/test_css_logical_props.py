"""[Patcher 8] CSS logical properties — RTL readiness (RTL-01, F-21).

Запрещает physical CSS-свойства:
  * margin-left/margin-right
  * padding-left/padding-right
  * border-left/border-right
  * inset-left/inset-right
  * bare left:/right: — кроме allowlist (handles + edge geometry).

Разрешено (allowlist):
  * .handle-{nw,ne,sw,se,n,s,e,w}
  * .box-edge-{n,s,e,w}
  * @media (pointer: coarse) handle/edge overrides
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "style.css"

# Геометрические селекторы — left/right физические и остаются.
_ALLOWED_SELECTORS = {
    ".handle-nw", ".handle-ne", ".handle-sw", ".handle-se",
    ".handle-n", ".handle-s", ".handle-e", ".handle-w",
    ".box-edge-n", ".box-edge-s", ".box-edge-e", ".box-edge-w",
}

# Значения, не влияющие на RTL (reset-семантика).
_RESET_VALUES = {"auto", "0", "0px", "0%", "inherit", "unset", "initial"}

_FORBIDDEN_PROPS = re.compile(
    r"(?<![\w-])(margin-left|margin-right|padding-left|padding-right|"
    r"border-left|border-right|inset-left|inset-right)\s*:"
)

# bare left:/right: — с allowlist по селектору
_BARE_LR = re.compile(r"(?<![\w-])(left|right)\s*:\s*([^;}\n]+)")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _iter_rules(css: str):
    """Yield (selector, body) для innermost CSS-правил."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        yield m.group(1).strip(), m.group(2)


def _selector_allowed(selector: str) -> bool:
    for allowed in _ALLOWED_SELECTORS:
        if allowed in selector:
            return True
    return False


def test_no_forbidden_physical_margin_padding_border():
    css = _strip_comments(CSS.read_text(encoding="utf-8"))
    offenders = []
    for sel, body in _iter_rules(css):
        for m in _FORBIDDEN_PROPS.finditer(body):
            offenders.append(f"{sel} → {m.group(1)}")
    assert not offenders, (
        "Physical margin/padding/border/inset-left/right found "
        "(use logical equivalents):\n" + "\n".join(offenders[:20])
    )


def test_no_bare_left_right_outside_allowlist():
    css = _strip_comments(CSS.read_text(encoding="utf-8"))
    offenders = []
    for sel, body in _iter_rules(css):
        if _selector_allowed(sel):
            continue
        for m in _BARE_LR.finditer(body):
            prop, val = m.group(1), m.group(2).strip()
            if val in _RESET_VALUES:
                continue
            offenders.append(f"{sel} → {prop}: {val}")
    assert not offenders, (
        "Bare left/right outside allowlist (use inset-inline-start/end):\n"
        + "\n".join(offenders[:20])
    )


def test_no_physical_props_in_handles():
    """Handles остаются физическими (привязаны к геометрии рамки)."""
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    for handle in (".handle-nw", ".handle-ne", ".handle-sw", ".handle-se"):
        pat = re.compile(
            re.escape(handle) + r"\s*\{([^}]*)\}", re.DOTALL
        )
        m = pat.search(css)
        assert m, f"{handle} not found in style.css"
        body = m.group(1)
        assert "inset-inline" not in body, (
            f"{handle} должен оставаться physical "
            f"(inset-inline сломает ресайз)"
        )


def test_no_physical_margin_in_inline_styles():
    """inline-style="margin-left/right" в index.html → fail."""
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    style_re = re.compile(r'style\s*=\s*"([^"]*)"', re.IGNORECASE)
    offenders = []
    for m in style_re.finditer(html):
        body = m.group(1)
        if "margin-left" in body or "margin-right" in body:
            offenders.append(body[:80])
    assert not offenders, (
        "Physical margin-left/right in inline-style "
        f"({len(offenders)} cases): {offenders[:5]}"
    )
