"""Stage 3: command palette — no View Transitions, standard modal animation."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_open_command_palette_no_with_view_transition():
    src = (ROOT / "js" / "command_palette.js").read_text(encoding="utf-8")
    assert "withViewTransition" not in src, (
        "js/command_palette.js всё ещё использует withViewTransition — "
        "Stage 3 не применён (палитра будет мигать)"
    )


def _js_function_body(src: str, name: str) -> str:
    """Extract body of `export function NAME(...) { ... }` via brace walker.

    Helper so the test can inspect the function body, not the whole file —
    a grep across the file used to false-pass because `:scope > .command-palette`
    was already present in closeModal (but not in openModal).
    """
    import re as _re
    pat = _re.compile(
        r"export\s+function\s+" + _re.escape(name) + r"\s*\([^)]*\)"
    )
    m = pat.search(src)
    if not m:
        return ""
    brace_start = src.find("{", m.end())
    if brace_start < 0:
        return ""
    depth = 0
    i = brace_start
    in_str = None
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ('"', "'", "`"):
            in_str = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[brace_start:i + 1]
        i += 1
    return ""


def test_open_modal_handles_command_palette():
    src = (ROOT / "js" / "ui.js").read_text(encoding="utf-8")
    body = _js_function_body(src, "openModal")
    assert body, "openModal function not found in js/ui.js"
    assert "querySelector(':scope > .command-palette')" in body, (
        "openModal не расширен на .command-palette — "
        "modal-animating не будет ставиться на палитру. "
        "Проверка идёт по телу openModal, а не по всему файлу "
        "(раньше проходила ложно из-за наличия строки в closeModal)."
    )


def test_command_palette_element_level_blur_disabled():
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    assert ".command-palette.modal-animating" in css, (
        ".command-palette.modal-animating не найден в style.css — "
        "backdrop-filter на самом .command-palette останется активным "
        "во время анимации (stutter при открытии палитры)."
    )
    m = re.search(
        r"\.command-palette\.modal-animating\s*\{([^}]*)\}",
        css, re.DOTALL,
    )
    assert m, ".command-palette.modal-animating block not found"
    body = m.group(1)
    assert "backdrop-filter: none" in body, (
        ".command-palette.modal-animating должен содержать backdrop-filter: none"
    )
    assert "-webkit-backdrop-filter: none" in body
