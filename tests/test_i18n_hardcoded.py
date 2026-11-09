"""[STAGE4:E4-I18N-HARD] no hardcoded RU in status/dialog calls.

Проверяет:
  * первый аргумент setX('...')/setX("...") начинается с кириллицы;
  * первый аргумент setX(`...`) содержит кириллицу;
  * второй аргумент setX(<expr>, '...'/'`...'/'"...') начинается с кириллицы;
  * [STAGE7] window.t('...') с кириллицей внутри — признак hardcoded-строки,
    переданной как ключ (а не как key в i18n).

Комментарии (// и /* */) игнорируются.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "js"

FUNCS = ("setStatus", "setError", "showConfirm", "showPrompt", "showAlert")

# [STAGE7] файлы, которые обязаны быть «чистыми» от window.t('...cyrillic...')
_STRICT_FILES = {
    "main.js", "keyboard.js", "command_palette.js",
}


def _strip_inline_comment(line: str) -> str:
    out = []
    in_str = None
    i = 0
    while i < len(line):
        ch = line[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ('"', "'", "`"):
                in_str = ch
                out.append(ch)
            elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                break
            else:
                out.append(ch)
        i += 1
    return "".join(out)


_RU = r"\u0410-\u044f\u0401\u0451"
_PAT_FIRST = re.compile(rf"\b(?:{'|'.join(FUNCS)})\s*\(\s*['\"]{_RU}")
_PAT_BACKTICK = re.compile(rf"\b(?:{'|'.join(FUNCS)})\s*\(\s*`[^`]*[{_RU}][^`]*`")
_PAT_SECOND = re.compile(rf"\b(?:{'|'.join(FUNCS)})\s*\([^,)]*,\s*['\"`][{_RU}]")
# [STAGE7] window.t('...cyrillic...') — текст вместо key
_PAT_WINDOW_T = re.compile(rf"\bwindow\.t\s*\(\s*['\"`][{_RU}]")


def _iter_offenders():
    for js_file in sorted(JS_DIR.rglob("*.js")):
        rel = js_file.relative_to(ROOT)
        if "vendor" in rel.parts or rel.name == "i18n-fallback.js":
            continue
        text = js_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
                continue
            code = _strip_inline_comment(line).strip()
            if not code:
                continue
            hits = (
                _PAT_FIRST.search(code)
                or _PAT_BACKTICK.search(code)
                or _PAT_SECOND.search(code)
                or _PAT_WINDOW_T.search(code)
            )
            if hits:
                yield f"{rel}:{line_no}: {line.strip()[:100]}"


def test_no_hardcoded_russian_in_status_calls():
    offenders = list(_iter_offenders())
    assert not offenders, (
        "Hardcoded RU in setStatus/setError/showConfirm/showPrompt/showAlert "
        "or window.t('...cyrillic...'):\n"
        + "\n".join(offenders)
    )


def test_no_cyrillic_window_t_in_strict_files():
    """[STAGE7] window.t('...cyrillic...') в main/keyboard/command_palette — запрещён.

    window.t ожидает ключ вида 'blur.mode_on', а не текст. Если в вызов
    попадает кириллица — это либо забытая замена, либо случайный hardcode.
    """
    offenders = []
    for fname in _STRICT_FILES:
        p = JS_DIR / fname
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            code = _strip_inline_comment(line)
            if _PAT_WINDOW_T.search(code):
                offenders.append(f"js/{fname}:{line_no}: {line.strip()[:100]}")
    assert not offenders, (
        "window.t('...cyrillic...') found in strict files:\n"
        + "\n".join(offenders)
    )


def test_no_cyrillic_in_js():
    """[STAGE7] общий smoke: ни в одном js-файле (кроме exceptions) нет
    window.t('...cyrillic...').

    Заменяет прежний список _DUP_RU (он проверял только версии diff).
    Теперь общий запрет для всего js/, кроме vendor/ и i18n-fallback.js.
    """
    offenders = []
    for js_file in sorted(JS_DIR.rglob("*.js")):
        rel = js_file.relative_to(ROOT)
        if "vendor" in rel.parts or rel.name == "i18n-fallback.js":
            continue
        text = js_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            code = _strip_inline_comment(line)
            if _PAT_WINDOW_T.search(code):
                offenders.append(f"{rel}:{line_no}: {line.strip()[:100]}")
    assert not offenders, (
        "window.t('...cyrillic...') found:\n" + "\n".join(offenders)
    )
