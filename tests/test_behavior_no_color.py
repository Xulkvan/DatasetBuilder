"""Patcher 3 — behaviors are monochrome (DS-02, Q4 = A).

Запрещено:
  * `[data-beh="..."]` селекторы с color/background/border-color;
  * `--beh-icon` mask-based per-type иконки;
  * `data-beh="eat"` / `"walk"` / ... selector с цветом.
"""
import re
from pathlib import Path


def _css() -> str:
    return (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")


def _js_main() -> str:
    return (Path(__file__).parent.parent / "js" / "main.js").read_text(encoding="utf-8")


def test_no_per_behavior_color_rules():
    css = _css()
    pattern = re.compile(r'\[data-beh="[^"]+"\][^{]*\{([^}]*)\}', re.DOTALL)
    for m in pattern.finditer(css):
        body = m.group(1).lower()
        for prop in ("background", "background-color", "color", "border-color"):
            pm = re.search(rf"\b{prop}\s*:\s*([^;]+);", body)
            if not pm:
                continue
            val = pm.group(1).strip()
            if val in ("currentcolor", "inherit", "transparent", "none"):
                continue
            if any(val.startswith(p) for p in (
                "var(--accent", "var(--text-secondary", "var(--text-primary",
            )):
                continue
            raise AssertionError(
                f"Per-behavior color rule: selector={m.group(0)[:100]!r} "
                f"property={prop} value={val}"
            )


def test_no_beh_icon_mask():
    css = _css()
    assert "--beh-icon" not in css, (
        "--beh-icon mask rules still present — use <svg><use href='#i-beh-...'/></svg>"
    )


def test_js_uses_svg_for_behaviors():
    """Behaviors must be rendered as SVG, not text/mask.

    Мы допускаем два варианта:
      (a) inline `createElementNS` + `#i-beh-*` прямо в теле функции;
      (b) вызов общего `_behSvg(...)` helper'а, который внутри себя
          делает и то, и другое.

    Второй вариант предпочтительнее (DRY) и используется в main.js после
    Patcher 3. Проверяем helper один раз + факт его вызова в 4 местах.
    """
    js = _js_main()
    # Helper _behSvg должен существовать и содержать SVG-примитивы
    assert "function _behSvg(" in js, "_behSvg helper not found"
    assert "createElementNS" in js, "SVG requires createElementNS"
    assert "#i-beh-" in js, "SVG sprite reference #i-beh-* missing"
    for fn_name in ("_createBoxElement", "updateBoxInPlace", "makeMainRow", "_updateRowContent"):
        idx = js.find(f"function {fn_name}(")
        assert idx >= 0, f"{fn_name} not found in main.js"
        end = js.find("\nfunction ", idx + 1)
        if end < 0:
            end = len(js)
        body = js[idx:end]
        assert "_behSvg(" in body, (
            f"{fn_name} must call _behSvg(...) to render behavior SVG icon"
        )
