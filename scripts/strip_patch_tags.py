#!/usr/bin/env python3
"""Strip patch anchors from source files — safe and idempotent.

What is removed
---------------
  Python:   ``# [PATCH:...]``, ``# [/PATCH:...]``, ``# [STAGE...:...]``,
            ``# [STAGE-N]``, ``# [FIX:...]``, ``# [/FIX:...]``,
            ``# [FRONTEND:...]``, ``# [PERF:...]``, ``# [BACKUP]``,
            ``# [QUALITY-...]``, ``# [DEAD-...]``, ``# [V<ver>:...]``
  JS/TS:    same tags but with ``//`` comment prefix.
  HTML:     single-line ``<!-- [PATCH:...] -->`` / ``<!-- [STAGE...] -->`` /
            ``<!-- [V<ver>:...] -->``.

Safety guarantees
-----------------
  * Never leaves bare text after stripping an anchor token.
  * Never deletes a line that contains code — only the comment part
    is removed when there is code before the comment marker.
  * Skips (never touches):
      - ``_MIGRATIONS`` in ``app.py``;
      - first line of ``app.py`` (``# [PATCH:STAGE7-ensure-schema]``);
      - docstrings in ``tests/*.py``;
      - ``.md``, ``.css``, ``vendor/``, runtime dirs, ``scripts/``;
      - this script itself.
  * Idempotent — running twice is a no-op.
  * Preserves original EOL (LF vs CRLF).

Two modes
---------
  safe (default):
      ``# [PATCH:X] some text``  ->  ``# some text``
      ``x = 1  # [PATCH:X]``     ->  ``x = 1``
      ``# [PATCH:X]``            ->  (line deleted, comment became empty)

  --prune (aggressive):
      ``# [PATCH:X] some text``  ->  (whole line deleted)
      ``x = 1  # [PATCH:X] text``->  ``x = 1``
      ``# [PATCH:X]``            ->  (line deleted)

  Use --prune when you are sure anchor descriptions are only breadcrumbs
  and you want clean output. Use default (safe) when uncertain — you can
  always clean leftover text manually.

Usage
-----
    python scripts/strip_patch_tags.py                    # dry-run, safe
    python scripts/strip_patch_tags.py --apply            # apply, safe
    python scripts/strip_patch_tags.py --prune --apply    # apply, aggressive
    python scripts/strip_patch_tags.py --apply path1 path2

Recommended flow
----------------
    git status                                # ensure clean tree
    python scripts/strip_patch_tags.py > /tmp/report.txt
    # review report
    python scripts/strip_patch_tags.py --apply
    git diff                                  # review changes
    python -m compileall app.py services routers
    node --check js/*.js js/**/*.js 2>/dev/null || true
    pytest -q -m "not slow and not ml"
    git checkout -- .                         # revert if something is wrong
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Anchor token pattern
# ---------------------------------------------------------------------------
# Matches a complete anchor token, e.g.:
#   [PATCH:STAGE6-F15-C18]      [/PATCH:STAGE3_ANNS_WITH_KP_CHUNKED]
#   [STAGE1:cli]                [STAGE-SEC1]  [STAGE-SEC1]:check:foo
#   [STAGE2_1:track-metrics]    [STAGE3B-BACKUP-DEPRECATE]
#   [FIX:bootstrap-thread-dead] [/FIX:heartbeat]
#   [FRONTEND:new-features-i18n] [PERF:modulepreload]
#   [BACKUP]                    [QUALITY-F2-CLEANUP]
#   [DEAD-PARSERS-REMOVAL]      [UI_MODES]
#   [V13.1.0:stats-ui]          [V14.5.4]
#
# Also matches trailing ``:foo:bar`` suffix (used for ``[STAGE-SEC1]:check:foo``
# where the tag is ``[STAGE-SEC1]`` and the suffix is ``:check:foo``).
_TAG_NAMES = (
    r"PATCH"
    r"|STAGE[A-Za-z0-9_.\-]*"
    r"|FIX"
    r"|FRONTEND"
    r"|PERF"
    r"|SEC"
    r"|BACKUP"
    r"|QUALITY[A-Za-z0-9_\-]*"
    r"|DEAD[A-Za-z0-9_\-]*"
    r"|UI_MODES"
    r"|V\d+(?:\.\d+)*"
)
_ANCHOR_RE = re.compile(
    r"\[\s*/?(?:" + _TAG_NAMES + r")(?::[^\[\]]*)?\]"
    r"(?::[A-Za-z0-9_\-.]+)*"
)


# ---------------------------------------------------------------------------
# Comment styles per extension
# ---------------------------------------------------------------------------
_COMMENT_STYLES: dict[str, tuple[str, str]] = {
    ".py":   ("#", ""),
    ".js":   ("//", ""),
    ".ts":   ("//", ""),
    ".html": ("<!--", "-->"),
}

_SCAN_EXTS = frozenset(_COMMENT_STYLES.keys())
_SKIP_EXTS = frozenset({".md", ".css", ".min.js", ".min.css", ".map"})


# ---------------------------------------------------------------------------
# Per-language comment detection (quote-aware)
# ---------------------------------------------------------------------------
def _find_python_comment(line: str) -> int:
    """Return index of the ``#`` that starts a comment, or -1."""
    in_s = in_d = False
    esc = False
    for i, ch in enumerate(line):
        if esc:
            esc = False
            continue
        if ch == "\\" and (in_s or in_d):
            esc = True
            continue
        if ch == "'" and not in_d:
            in_s = not in_s
            continue
        if ch == '"' and not in_s:
            in_d = not in_d
            continue
        if ch == "#" and not in_s and not in_d:
            return i
    return -1


def _find_js_comment(line: str) -> int:
    """Return index of the ``//`` that starts a comment, or -1."""
    in_s = in_d = in_t = False
    esc = False
    i = 0
    while i < len(line) - 1:
        ch = line[i]
        if esc:
            esc = False
            i += 1
            continue
        if ch == "\\" and (in_s or in_d or in_t):
            esc = True
            i += 1
            continue
        if ch == "'" and not in_d and not in_t:
            in_s = not in_s
            i += 1
            continue
        if ch == '"' and not in_s and not in_t:
            in_d = not in_d
            i += 1
            continue
        if ch == "`" and not in_s and not in_d:
            in_t = not in_t
            i += 1
            continue
        if (ch == "/" and not in_s and not in_d and not in_t
                and line[i + 1] == "/"):
            return i
        i += 1
    return -1


def _find_comment_span(line: str, ext: str) -> tuple[int, int] | None:
    """Return (start, end_exclusive) of the comment span, or None."""
    if ext == ".py":
        i = _find_python_comment(line)
        if i < 0:
            return None
        return (i, len(line))
    if ext in (".js", ".ts"):
        i = _find_js_comment(line)
        if i < 0:
            return None
        return (i, len(line))
    if ext == ".html":
        i = line.find("<!--")
        if i < 0:
            return None
        j = line.find("-->", i + 4)
        if j < 0:
            # multi-line comment — do not touch (safe)
            return None
        return (i, j + 3)
    return None


# ---------------------------------------------------------------------------
# Anchor stripping
# ---------------------------------------------------------------------------
def _strip_anchor_tokens(text: str) -> str:
    """Remove all anchor tokens from *text*; normalise whitespace."""
    out = _ANCHOR_RE.sub("", text)
    out = re.sub(r"[ \t]+", " ", out).strip()
    return out


def _process_line(line: str, ext: str, prune: bool) -> str | None:
    """Return new line (str), or ``None`` to delete the line."""
    span = _find_comment_span(line, ext)
    if span is None:
        return line

    c_start, c_end = span
    prefix, suffix = _COMMENT_STYLES[ext]
    code_part = line[:c_start]
    comment_span = line[c_start:c_end]

    # Extract inner text of the comment (strip prefix and suffix markers).
    inner = comment_span[len(prefix):]
    if suffix and inner.endswith(suffix):
        inner = inner[:-len(suffix)]
    inner_stripped = inner.strip()

    # No anchor at all — nothing to do.
    if not _ANCHOR_RE.search(inner_stripped):
        return line

    has_code = bool(code_part.strip())
    starts_with_anchor = _ANCHOR_RE.match(inner_stripped) is not None

    # ─── inline comment (code before marker) ──────────────────────────────
    if has_code:
        if prune and starts_with_anchor:
            return code_part.rstrip()
        new_inner = _strip_anchor_tokens(inner_stripped)
        if new_inner:
            return (
                code_part.rstrip()
                + "  " + prefix + " " + new_inner + suffix
            )
        return code_part.rstrip()

    # ─── standalone comment (whole line is comment) ───────────────────────
    indent = line[:len(line) - len(line.lstrip())]

    if prune and starts_with_anchor:
        return None  # delete whole comment line

    new_inner = _strip_anchor_tokens(inner_stripped)
    if new_inner:
        return indent + prefix + " " + new_inner + suffix
    return None  # comment became empty — delete the line


# ---------------------------------------------------------------------------
# Protected ranges (never touched)
# ---------------------------------------------------------------------------
def _find_migrations_range(lines: list[str]) -> tuple[int, int] | None:
    """Locate ``_MIGRATIONS = [ ... ]`` range (0-indexed, inclusive)."""
    start: int | None = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*_MIGRATIONS\s*=\s*\[", line):
            start = i
            break
    if start is None:
        return None
    for i in range(start, len(lines)):
        if re.match(r"^\]", lines[i]):
            return (start, i)
    return None


def _docstring_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """1-indexed inclusive ranges covered by triple-quoted strings (``\"\"\"``)."""
    ranges: list[tuple[int, int]] = []
    in_ds = False
    ds_start = 0
    for i, line in enumerate(lines, start=1):
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


def _compute_skip_indices(lines: list[str], path: Path) -> set[int]:
    """0-indexed line numbers that must never be modified."""
    skip: set[int] = set()

    if path.name == "app.py":
        if lines and "[PATCH:STAGE7-ensure-schema]" in lines[0]:
            skip.add(0)
        mig = _find_migrations_range(lines)
        if mig:
            start, end = mig
            for i in range(start, end + 1):
                skip.add(i)
            if (end + 1 < len(lines)
                    and lines[end + 1].strip().startswith("# [STAGE0:")):
                skip.add(end + 1)

    if path.parent.name == "tests" or "tests" in path.parts:
        for a, b in _docstring_ranges(lines):
            for i in range(a - 1, b):
                skip.add(i)

    return skip


# ---------------------------------------------------------------------------
# Paths to skip entirely
# ---------------------------------------------------------------------------
_SKIP_DIR_PARTS = frozenset({
    ".git", ".backups", ".venv", "venv", "node_modules",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "data", "uploads", "thumbs", "models", "exports", "runs",
    "videos", "imports", "backups", "dist", "build", "htmlcov",
    "scripts",
})


def _is_skip_path(p: Path) -> bool:
    parts = set(p.parts)
    if parts & _SKIP_DIR_PARTS:
        return True
    if "vendor" in parts:
        return True
    if p.name in {"test_strip_patch_tags.py", "purify.min.js"}:
        return True
    if p.suffix in _SKIP_EXTS:
        return True
    # match_glob for *.min.js (suffix only sees .js, not .min.js)
    if p.name.endswith((".min.js", ".min.css")):
        return True
    return False


# ---------------------------------------------------------------------------
# File read/write preserving EOL
# ---------------------------------------------------------------------------
def _read_text(path: Path) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _detect_eol(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text:
        return "\r"
    return "\n"


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------
def process_file(path: Path, *, dry_run: bool, prune: bool) -> tuple[int, int]:
    """Return (deleted_lines, modified_lines)."""
    ext = path.suffix.lower()
    if ext not in _COMMENT_STYLES:
        return (0, 0)

    src = _read_text(path)
    if src is None:
        return (0, 0)

    eol = _detect_eol(src)
    lines = src.split(eol)
    skip = _compute_skip_indices(lines, path)

    deleted = modified = 0
    out: list[str] = []

    for i, line in enumerate(lines):
        if i in skip:
            out.append(line)
            continue
        new = _process_line(line, ext, prune=prune)
        if new is None:
            deleted += 1
        elif new != line:
            modified += 1
            out.append(new)
        else:
            out.append(line)

    new_src = eol.join(out)
    if new_src == src:
        return (0, 0)

    if not dry_run:
        _write_text(path, new_src)
    return (deleted, modified)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _collect_targets(cli_paths: list[str]) -> list[Path]:
    if cli_paths:
        result: list[Path] = []
        for p in cli_paths:
            pp = Path(p).resolve()
            if pp.is_file():
                if pp.suffix.lower() in _SCAN_EXTS and not _is_skip_path(pp):
                    result.append(pp)
            elif pp.is_dir():
                for sub in pp.rglob("*"):
                    if (sub.is_file()
                            and sub.suffix.lower() in _SCAN_EXTS
                            and not _is_skip_path(sub)):
                        result.append(sub)
        return sorted(set(result))

    result = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in _SCAN_EXTS:
            continue
        if _is_skip_path(p):
            continue
        result.append(p)
    return sorted(result)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Strip patch anchors from source files (safe + idempotent).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Modes:\n"
            "  safe (default):  '# [PATCH:X] text'  ->  '# text'\n"
            "                   '# [PATCH:X]'       ->  (line deleted)\n"
            "                   'x = 1  # [PATCH:X]'-> 'x = 1'\n"
            "  --prune:         '# [PATCH:X] text'  ->  (line deleted)\n"
            "                   'x = 1  # [PATCH:X] text' -> 'x = 1'\n"
            "\n"
            "Default is dry-run. Use --apply to actually modify files."
        ),
    )
    ap.add_argument(
        "--apply", action="store_true",
        help="Actually modify files (default: dry-run).",
    )
    ap.add_argument(
        "--prune", action="store_true",
        help="If a comment starts with an anchor, delete the whole comment "
             "(including any description text). Default keeps description.",
    )
    ap.add_argument(
        "--quiet", "-q", action="store_true",
        help="Only print summary (no per-file lines).",
    )
    ap.add_argument(
        "paths", nargs="*", default=None,
        help="Optional paths (files or directories). "
             "Default: scan ROOT recursively.",
    )
    args = ap.parse_args()

    targets = _collect_targets(args.paths or [])

    total_del = total_mod = touched = 0
    for p in targets:
        deleted, modified = process_file(
            p, dry_run=not args.apply, prune=args.prune,
        )
        if deleted or modified:
            touched += 1
            total_del += deleted
            total_mod += modified
            if not args.quiet:
                try:
                    rel = p.relative_to(ROOT)
                except ValueError:
                    rel = p
                tag = "[apply]" if args.apply else "[dry]"
                print(f"{tag} {rel}: deleted={deleted}, modified={modified}")

    print()
    print(f"Files touched: {touched}")
    print(f"Lines deleted: {total_del}, lines modified: {total_mod}")
    mode = "prune" if args.prune else "safe"
    print(f"Mode: {mode}")
    if not args.apply and (total_del or total_mod):
        print()
        print("Dry-run only. Run with --apply to actually modify files.")
        print("Recommended: ensure `git status` is clean before --apply, "
              "then review `git diff`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
