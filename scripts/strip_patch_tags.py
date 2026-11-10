#!/usr/bin/env python3
"""[STAGE8] Strip patch anchors from source files.

Удаляет маркеры:
  * `# [PATCH:…]`
  * `# [STAGE<N>:…]`
  * `// [FIX:…]`
  * `<!-- [V…:…] -->`

НЕ трогает:
  * `_MIGRATIONS` в app.py (по номерам строк);
  * docstrings в tests/*.py;
  * `.md`, `.css`;
  * строку `# [PATCH:STAGE7-ensure-schema]` в первой строке app.py.

Пары (`# [PATCH:X] … # [/PATCH:X]`) удаляются обе.
Inline (`x = 1  # [PATCH:X]`) — только хвост, код сохраняется.

По умолчанию dry-run; `--apply` — реальное удаление.

Usage:
    python scripts/strip_patch_tags.py            # dry-run
    python scripts/strip_patch_tags.py --apply    # apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Регексы для поиска анкоров
_ANCHOR_PATTERNS = [
    re.compile(r"#\s*\[PATCH:[^\]]+\]"),                    # # [PATCH:…]
    re.compile(r"#\s*\[/PATCH:[^\]]+\]"),                   # # [/PATCH:…]
    re.compile(r"#\s*\[STAGE\d+[^\]]*\]"),                  # # [STAGE<N>:…]
    re.compile(r"//\s*\[FIX:[^\]]+\]"),                     # // [FIX:…]
    re.compile(r"//\s*\[/FIX:[^\]]+\]"),                    # // [/FIX:…]
    re.compile(r"<!--\s*\[V[\d.]+:[^\]]+\]\s*-->"),         # <!-- [V…:…] -->
]

_PAIRED_RE = re.compile(r"#\s*\[(/?)PATCH:([A-Za-z0-9_\-:.]+)\]")
_PAIRED_FIX_RE = re.compile(r"//\s*\[(/?)FIX:([A-Za-z0-9_\-:.]+)\]")

_SKIP_EXTS = {".md", ".css", ".min.js", ".min.css"}
_SKIP_NAMES = {"purify.min.js"}

_SCAN_EXTS = {".py", ".js", ".html", ".ts"}


def _is_skip_path(p: Path) -> bool:
    parts = set(p.parts)
    if parts & {".git", ".backups", ".venv", "venv", "node_modules",
                "__pycache__", ".mypy_cache", ".pytest_cache",
                ".ruff_cache", "data", "uploads", "thumbs",
                "models", "exports", "runs", "videos", "imports",
                "backups"}:
        return True
    if p.suffix in _SKIP_EXTS:
        return True
    if p.name in _SKIP_NAMES:
        return True
    if "vendor" in parts:
        return True
    return False


def _find_migrations_range(lines: list[str]) -> tuple[int, int] | None:
    """_MIGRATIONS = [ ... ] — возвращает (start_idx, end_idx) или None."""
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*_MIGRATIONS\s*=\s*\[", line):
            start = i
            break
    if start is None:
        return None
    # Ищем закрывающую ] начиная со start
    for i in range(start, len(lines)):
        if re.match(r"^\]", lines[i]):
            return (start, i)
    return None


def _docstring_ranges(source: str) -> list[tuple[int, int]]:
    """Внутренности `\"\"\"...\"\"\"` как диапазоны строк (1-indexed)."""
    ranges: list[tuple[int, int]] = []
    lines = source.split("\n")
    in_ds = False
    ds_start = 0
    for i, line in enumerate(lines, start=1):
        # Грубая эвристика: `"""` открывает/закрывает
        n = line.count('"""')
        if n == 0:
            continue
        if not in_ds:
            in_ds = True
            ds_start = i
            if n >= 2:
                ranges.append((ds_start, i))
                in_ds = False
        else:
            ranges.append((ds_start, i))
            in_ds = False
    return ranges


def _in_ranges(line_no: int, ranges: list[tuple[int, int]]) -> bool:
    return any(a <= line_no <= b for a, b in ranges)


def _strip_paired(lines: list[str]) -> tuple[list[str], int]:
    """Удаляет парные `[PATCH:X]` … `[/PATCH:X]` (обе строки)."""
    removed = 0
    # Соберём открывающие маркеры с их именем
    stack: dict[str, list[int]] = {}
    delete_marks: set[int] = set()
    for i, line in enumerate(lines):
        for m in _PAIRED_RE.finditer(line):
            is_close = bool(m.group(1))
            name = m.group(2)
            if not is_close:
                stack.setdefault(name, []).append(i)
            else:
                opens = stack.get(name, [])
                if opens:
                    open_i = opens.pop()
                    # Если строка — только анкор, удаляем целиком.
                    # Если inline — только хвост (для простоты считаем анкором
                    # хвост от # до конца строки).
                    # open line
                    line_open = lines[open_i]
                    stripped_open = line_open.strip()
                    if stripped_open == line_open.lstrip() and \
                            not stripped_open.split("#")[0].strip():
                        # Ведущий (возможно с отступом) анкор — удаляем целиком
                        delete_marks.add(open_i)
                    else:
                        # inline: обрезаем хвост
                        lines[open_i] = re.sub(
                            r"#\s*\[PATCH:[^\]]+\]\s*$", "", line_open).rstrip()
                    line_close = lines[i]
                    stripped_close = line_close.strip()
                    if not stripped_close.split("#")[0].strip():
                        delete_marks.add(i)
                    else:
                        lines[i] = re.sub(
                            r"#\s*\[/PATCH:[^\]]+\]\s*$", "", line_close).rstrip()
        # same for FIX
        for m in _PAIRED_FIX_RE.finditer(line):
            is_close = bool(m.group(1))
            name = "FIX:" + m.group(2)
            if not is_close:
                stack.setdefault(name, []).append(i)
            else:
                opens = stack.get(name, [])
                if opens:
                    open_i = opens.pop()
                    delete_marks.add(open_i)
                    delete_marks.add(i)
    new_lines = [ln for i, ln in enumerate(lines) if i not in delete_marks]
    removed += len(delete_marks)
    return new_lines, removed


def _strip_standalone(lines: list[str],
                      skip_lines: set[int]) -> tuple[list[str], int]:
    """Удаляет standalone анкоры (строка начинается с анкора) и inline хвосты."""
    removed = 0
    out: list[str] = []
    for i, line in enumerate(lines):
        if i in skip_lines:
            out.append(line)
            continue
        # Проверим, есть ли анкор
        matched_any = False
        # Парные уже обработаны — здесь только одиночные
        stripped = line.lstrip()
        leading_ws = line[:len(line) - len(stripped)]
        # Standalone: строка начинается с анкора (плюс возможные комментарии)
        standalone = False
        for pat in _ANCHOR_PATTERNS:
            m = pat.match(stripped)
            if m:
                # Если после анкора только пробелы — строка standalone
                tail = stripped[m.end():].strip()
                if not tail:
                    standalone = True
                break
        if standalone:
            removed += 1
            continue
        # Inline: удаляем только ` # [PATCH:…]` в конце
        new_line = line
        for pat in _ANCHOR_PATTERNS:
            new_line = pat.sub("", new_line).rstrip()
            if new_line != line:
                matched_any = True
                break
        if matched_any:
            # Если после удаления остались только отступы — удалить строку
            if not new_line.strip():
                removed += 1
                continue
            removed += 1
            out.append(new_line)
        else:
            out.append(line)
    return out, removed


def process_file(path: Path, dry_run: bool) -> tuple[int, int]:
    """Возвращает (removed_count, skipped_count)."""
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return (0, 1)
    original = src
    lines = src.split("\n")

    # Спец. защита app.py
    skip_lines: set[int] = set()
    if path.name == "app.py":
        # Первая строка `# [PATCH:STAGE7-ensure-schema]` — не трогать
        if lines and "[PATCH:STAGE7-ensure-schema]" in lines[0]:
            skip_lines.add(0)
        mig = _find_migrations_range(lines)
        if mig:
            start, end = mig
            for i in range(start, end + 1):
                skip_lines.add(i)
            # + следующая строка если это `# [STAGE0:auth-migrations-list]`
            if end + 1 < len(lines) and lines[end + 1].strip().startswith(
                    "# [STAGE0:"):
                skip_lines.add(end + 1)

    # Спец. защита tests/*.py — docstrings
    if path.parent.name == "tests" or "tests" in path.parts:
        for a, b in _docstring_ranges(src):
            for i in range(a - 1, b):
                skip_lines.add(i)

    # Шаг 1: парные
    new_lines, removed_paired = _strip_paired(lines)
    # Пересчитать skip_lines (индексы сдвинулись) — для простоты
    # пересчитаем заново на new_lines
    skip_lines2: set[int] = set()
    if path.name == "app.py":
        if new_lines and "[PATCH:STAGE7-ensure-schema]" in new_lines[0]:
            skip_lines2.add(0)
        mig = _find_migrations_range(new_lines)
        if mig:
            for i in range(mig[0], mig[1] + 1):
                skip_lines2.add(i)
            if mig[1] + 1 < len(new_lines) and new_lines[mig[1] + 1].strip().startswith("# [STAGE0:"):
                skip_lines2.add(mig[1] + 1)
    if path.parent.name == "tests" or "tests" in path.parts:
        for a, b in _docstring_ranges("\n".join(new_lines)):
            for i in range(a - 1, b):
                skip_lines2.add(i)

    # Шаг 2: одиночные / inline
    new_lines2, removed_standalone = _strip_standalone(new_lines, skip_lines2)

    removed = removed_paired + removed_standalone
    new_src = "\n".join(new_lines2)
    if new_src == original:
        return (0, 0)
    if dry_run:
        return (removed, 0)
    path.write_text(new_src, encoding="utf-8")
    return (removed, 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("paths", nargs="*", default=None)
    args = ap.parse_args()

    if args.paths:
        targets = [Path(p) for p in args.paths]
    else:
        targets = []
        for p in ROOT.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in _SCAN_EXTS:
                continue
            if _is_skip_path(p):
                continue
            targets.append(p)

    total_removed = 0
    total_skipped = 0
    for p in targets:
        removed, skipped = process_file(p, dry_run=not args.apply)
        if removed:
            rel = p.relative_to(ROOT) if p.is_relative_to(ROOT) else p
            print(f"{'[apply]' if args.apply else '[dry]'} {rel}: {removed} anchor(s)")
            total_removed += removed
        if skipped:
            total_skipped += skipped
    print(f"\nTotal removed: {total_removed}, skipped files: {total_skipped}")
    if not args.apply and total_removed:
        print("Run with --apply to actually delete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
