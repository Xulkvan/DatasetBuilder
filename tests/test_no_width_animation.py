"""Patcher 4 — no non-compositor transitions in style.css.

Запрещено: `transition: width|height|top|left|right|bottom|margin|padding`
(GPU/CPU layout thrashing). Только `transform` и `opacity`.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = ROOT / "style.css"
BAD_PROPS = "width|height|top|left|right|bottom|margin|padding"
PATTERN = re.compile(
    r"transition:\s*(?:[^;]*\s)?(?:" + BAD_PROPS + r")\b",
    re.IGNORECASE,
)


def test_no_width_animation_in_css():
    css = CSS_PATH.read_text(encoding="utf-8")
    # strip CSS comments (кроме @allow-animate-width маркеров)
    stripped = []
    i = 0
    while i < len(css):
        if css.startswith("/*", i):
            end = css.find("*/", i + 2)
            if end < 0:
                break
            inner = css[i:end + 2]
            if "@allow-animate-width" in inner:
                stripped.append(inner)
            i = end + 2
            continue
        stripped.append(css[i])
        i += 1
    code = "".join(stripped)

    matches = PATTERN.findall(code)
    assert not matches, (
        f"Найдены non-compositor transitions: {matches}. "
        f"Используйте только transform/opacity."
    )


def test_progress_bars_use_scaleX():
    css = CSS_PATH.read_text(encoding="utf-8")
    for sel in (".progress-fill", ".train-progress-fill",
                ".migrate-fill", ".histo-bar"):
        pat = re.compile(
            r"^" + re.escape(sel) + r"\s*\{([^}]*)\}",
            re.MULTILINE | re.DOTALL,
        )
        m = pat.search(css)
        assert m, f"{sel} rule not found"
        body = m.group(1)
        assert "transform: scaleX(var(--progress" in body, (
            f"{sel} must use `transform: scaleX(var(--progress, 0))`"
        )
        assert "transition: transform" in body, (
            f"{sel} must transition `transform`, not width"
        )
