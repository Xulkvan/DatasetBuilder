"""Patcher 7 — no emoji in UI files (DS-03, F-12, F-16, A11Y-04).

Запрещены emoji в UI-файлах:
  * index.html
  * i18n.js
  * js/main.js
  * js/*.js (кроме js/changelog.js)

Разрешено:
  * js/changelog.js — исторический лог (документ, не UI);
  * training-log-строки в js/main.js с комментарием `// @allow-emoji-log`.

Все иконки должны быть `<svg><use href="#i-..."/></svg>` из общего спрайта.
"""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

# Эмодзи-диапазоны Unicode (все блоки, где встречаются UI-эмодзи).
EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001F02F"   # Mahjong / Dominoes / Cards
    "\U0001F0A0-\U0001F0FF"   # Playing Cards
    "\U0001F100-\U0001F1FF"   # Enclosed Alphanumeric Supplement
    "\U0001F200-\U0001F2FF"   # Enclosed Ideographic Supplement
    "\U0001F300-\U0001F5FF"   # Misc Symbols and Pictographs
    "\U0001F600-\U0001F64F"   # Emoticons
    "\U0001F650-\U0001F67F"   # Ornamental Dingbats
    "\U0001F680-\U0001F6FF"   # Transport and Map Symbols
    "\U0001F700-\U0001F77F"   # Alchemical Symbols
    "\U0001F780-\U0001F7FF"   # Geometric Shapes Extended
    "\U0001F800-\U0001F8FF"   # Supplemental Arrows-C
    "\U0001F900-\U0001F9FF"   # Supplemental Symbols and Pictographs
    "\U0001FA00-\U0001FA6F"   # Chess Symbols
    "\U0001FA70-\U0001FAFF"   # Symbols and Pictographs Extended-A
    "\U00002600-\U000027BF"   # Misc Symbols + Dingbats
    "\U00002B00-\U00002BFF"   # Misc Symbols and Arrows
    "\U0000FE0F"               # VS16 (variation selector)
    "]"
)

TARGET_FILES = [
    "index.html",
    "i18n.js",
    "js/main.js",
]

SKIP_FILES = {
    "js/changelog.js",
    "js/i18n-fallback.js",
}

ALLOW_LINE_MARKERS = (
    "// @allow-emoji-log",
)

# Safety net: training-log строки содержат [train] в тексте; даже если
# @allow-emoji-log забыт — пропускаем (по плану Patcher 7: «в логах emoji
# оставляем»).
ALLOW_SUBSTRINGS = (
    "[train]",
)


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Возвращает [(line_no, line_text)] с эмодзи (без исключений)."""
    offenders: list[tuple[int, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if any(marker in line for marker in ALLOW_LINE_MARKERS):
            continue
        if any(sub in line for sub in ALLOW_SUBSTRINGS):
            continue
        if EMOJI_RE.search(line):
            offenders.append((i, line[:140]))
    return offenders


def _format(rel: str, offenders: list[tuple[int, str]]) -> list[str]:
    return [f"  {rel}:{i}: {line}" for i, line in offenders]


def test_no_emoji_in_index_html():
    p = ROOT / "index.html"
    assert p.exists(), f"{p} not found"
    offenders = _scan_file(p)
    assert not offenders, (
        "Emoji found in index.html — replace with <svg><use href=\"#i-...\"/></svg>:\n"
        + "\n".join(_format("index.html", offenders))
    )


def test_no_emoji_in_i18n_js():
    p = ROOT / "i18n.js"
    assert p.exists(), f"{p} not found"
    offenders = _scan_file(p)
    assert not offenders, (
        "Emoji found in i18n.js values — remove from string values:\n"
        + "\n".join(_format("i18n.js", offenders))
    )


def test_no_emoji_in_js_modules():
    js_dir = ROOT / "js"
    all_offenders: list[str] = []
    for path in sorted(js_dir.glob("*.js")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in SKIP_FILES:
            continue
        offenders = _scan_file(path)
        all_offenders.extend(_format(rel, offenders))
    assert not all_offenders, (
        "Emoji found in js modules — replace with <svg><use href=\"#i-...\"/></svg> "
        "or move to training-log (mark line with `// @allow-emoji-log`):\n"
        + "\n".join(all_offenders)
    )


def test_changelog_has_emoji_allowed():
    """Sanity: js/changelog.js существует и содержит эмодзи — exception из плана."""
    p = ROOT / "js" / "changelog.js"
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    assert EMOJI_RE.search(text), (
        "js/changelog.js не содержит эмодзи — либо файл переписан, либо регекс сломан. "
        "Emoji в changelog разрешены по плану Patcher 7."
    )
