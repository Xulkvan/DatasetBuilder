"""Patcher 4 / Stage 8 — @keyframes animates only compositor properties.

`@keyframes`, как и `transition`, не должны менять layout- или paint-свойства:
только `transform` и `opacity`. Иначе браузер пересчитывает layout/paint на
каждом кадре (row highlight, save-indicator pulse, skeleton pulse и т.п.).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = ROOT / "style.css"

ALLOWED = {"transform", "opacity"}


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _iter_keyframes(css: str):
    pattern = re.compile(r"@keyframes\s+([A-Za-z0-9_-]+)\s*\{")
    for match in pattern.finditer(css):
        depth = 1
        i = match.end()
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        yield match.group(1), css[match.end():i - 1]


def test_keyframes_use_only_transform_and_opacity():
    css = _strip_comments(CSS_PATH.read_text(encoding="utf-8"))
    bad = []
    for name, body in _iter_keyframes(css):
        for decl in re.findall(r"([a-z-]+)\s*:[^;{}]+", body):
            prop = decl.strip().lower()
            if prop and prop not in ALLOWED:
                bad.append(f"{name}: {prop}")
    assert not bad, (
        "Non-compositor properties in @keyframes: " + ", ".join(bad) + ". "
        "Use transform/opacity (or a pseudo-element overlay)."
    )


def test_keyframe_animations_are_present():
    css = _strip_comments(CSS_PATH.read_text(encoding="utf-8"))
    names = {name for name, _ in _iter_keyframes(css)}
    for expected in ("rowUpdated", "batchFlash", "indicatorPulse", "skeletonPulse"):
        assert expected in names, f"@keyframes {expected} missing"
