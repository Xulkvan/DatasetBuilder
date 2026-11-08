"""[STAGE4:E4-I18N-HARD] no hardcoded RU in status/dialog calls.

Проверяет:
  * первый аргумент setX('...')/setX("...") начинается с кириллицы;
  * первый аргумент setX(`...`) содержит кириллицу;
  * второй аргумент setX(<expr>, '...'/'`...'/'"...') начинается с кириллицы.

Комментарии (// и /* */) игнорируются.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "js"

FUNCS = ("setStatus", "setError", "showConfirm", "showPrompt", "showAlert")


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
            if not code or not any(fn + "(" in code for fn in FUNCS):
                continue
            if _PAT_FIRST.search(code) or _PAT_BACKTICK.search(code) or _PAT_SECOND.search(code):
                yield f"{rel}:{line_no}: {line.strip()[:100]}"


def test_no_hardcoded_russian_in_status_calls():
    offenders = list(_iter_offenders())
    assert not offenders, (
        "Hardcoded RU in setStatus/setError/showConfirm/showPrompt/showAlert:\n"
        + "\n".join(offenders)
    )
