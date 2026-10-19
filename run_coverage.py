#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_coverage.py — coverage-отчёт по целевым функциям DatasetBuilder.

Автоматически находит Python с зависимостями: .venv рядом с проектом,
у родителя, у деда, или через VIRTUAL_ENV/sys.executable.

Запуск:
    python run_coverage.py                # отчёт + htmlcov/
    python run_coverage.py --open         # ещё и открыть в браузере
    python run_coverage.py --targets app launcher --open
    python run_coverage.py --python path/to/python   # форсировать
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
COV_JSON = ROOT / "coverage.json"
HTML_DIR = ROOT / "htmlcov"


TARGETS = {
    "app.py": [
        ("get_annotations",                 "#1 order_by(Annotation.id)"),
        ("backup_project",                  "#2 backup: keypoints+attrs"),
        ("copy_annotations",                "#3 copy: чистка kp + attrs"),
        ("_apply_pose_detection_to_anns",   "#4 pose autolabel replace-safe"),
        ("_bulk_transfer",                  "#5 bulk copy: kp+attrs"),
        ("_process_dataset_zip",            "U1 import cancel"),
        ("import_cancel",                   "U2 /api/import/cancel"),
        ("_norm_behavior",                  "ref: поведение"),
        ("_iou_xywh",                       "ref: IoU"),
        ("_hex_to_int",                     "ref: pHash"),
        ("predict_behavior_from_keypoints", "ref: поведение по скелету"),
    ],
    "launcher.py": [
        ("_pick_data_root",                 "#7 логирование миграции"),
    ],
}


# ---------------------------------------------------------------------------
# Поиск Python с зависимостями
# ---------------------------------------------------------------------------
def _venv_bins(base: Path) -> list:
    if os.name == "nt":
        return [base / ".venv" / "Scripts" / "python.exe",
                base / "venv"  / "Scripts" / "python.exe"]
    return [base / ".venv" / "bin" / "python",
            base / "venv"  / "bin" / "python"]


def _candidate_pythons(explicit):
    out = []
    if explicit:
        out.append(Path(explicit))

    # .venv у проекта, у родителя и у деда — типичные раскладки.
    for base in (ROOT, ROOT.parent, ROOT.parent.parent):
        out.extend(_venv_bins(base))

    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        out.extend(_venv_bins(Path(venv)))

    if sys.executable:
        out.append(Path(sys.executable))

    seen = set()
    uniq = []
    for p in out:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


# Многострочный скрипт: __import__ реально грузит модуль и все его зависимости.
_PROBE = "\n".join([
    "import sys",
    "mods = ['pytest', 'pytest_cov', 'fastapi', 'uvicorn']",
    "missing = []",
    "for m in mods:",
    "    try:",
    "        __import__(m)",
    "    except Exception:",
    "        missing.append(m)",
    "print('|'.join(missing))",
    "sys.exit(0 if not missing else 1)",
])


def _probe_python(py: Path):
    if not py.exists():
        return False, "не найден"
    try:
        r = subprocess.run([str(py), "-c", _PROBE],
                           capture_output=True, text=True, timeout=30)
    except Exception as e:
        return False, "не запускается: %s" % e
    if r.returncode == 0:
        return True, ""
    missing = (r.stdout or "").strip().replace("|", ", ") or "(stderr: %s)" % ((r.stderr or "").strip().splitlines()[-1] if r.stderr else "")
    return False, "нет модулей: " + missing


def _pick_python(explicit):
    print("Поиск Python с зависимостями проекта:")
    for py in _candidate_pythons(explicit):
        ok, reason = _probe_python(py)
        mark = "✓" if ok else "✗"
        line = "  [%s] %s" % (mark, py)
        if not ok:
            line += "  — " + reason
        print(line)
        if ok:
            return py
    print()
    print("Ни один интерпретатор не подошёл. Что делать:")
    print("  1. Активируй venv:  ..\\.venv\\Scripts\\activate")
    print("     потом:           python run_coverage.py --targets app launcher --open")
    print("  2. Или явно:        python run_coverage.py --python ..\\.venv\\Scripts\\python.exe")
    print("  3. Или поставь:     pip install -r requirements.txt pytest pytest-cov")
    return None


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------
def _find_functions(py_path: Path):
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", None) or node.lineno
            out.setdefault(node.name, []).append((node.lineno, int(end)))
    return out


def _func_stats(ranges, executed, missing):
    ex = mi = 0
    for (a, b) in ranges:
        ex += sum(1 for ln in executed if a <= ln <= b)
        mi += sum(1 for ln in missing if a <= ln <= b)
    total = ex + mi
    pct = (100.0 * ex / total) if total else 0.0
    return {"executed": ex, "missing": mi, "total": total, "percent": pct}


# ---------------------------------------------------------------------------
# Запуск pytest
# ---------------------------------------------------------------------------
def _run_pytest(py: Path, targets, html: bool) -> int:
    cmd = [str(py), "-m", "pytest", "tests/"]
    for t in targets:
        cmd.append("--cov=" + t)
    cmd.append("--cov-report=json:" + COV_JSON.name)
    if html:
        cmd.append("--cov-report=html:" + HTML_DIR.name)
    cmd.append("-q")
    print()
    print("$ " + " ".join(cmd))
    print()
    t0 = time.time()
    r = subprocess.run(cmd, cwd=str(ROOT))
    print("\n[pytest: %.1fs, exit=%d]" % (time.time() - t0, r.returncode))
    return r.returncode


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------
def _load_cov():
    if not COV_JSON.exists():
        print("\n✗ %s не создан — coverage не собрался." % COV_JSON.name)
        return None
    try:
        return json.loads(COV_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        print("\n✗ Не могу прочитать %s: %s" % (COV_JSON.name, e))
        return None


def _file_info(cov_data, fname):
    for k, info in cov_data["files"].items():
        if Path(k).name == fname:
            return info
    return None


def _print_overall(cov_data):
    print("=" * 72)
    print("ОБЩЕЕ ПОКРЫТИЕ")
    print("=" * 72)
    print("%-28s %9s %10s %8s" % ("Файл", "Строк", "Покрыто", "%"))
    print("-" * 72)
    for fname in sorted(cov_data["files"].keys(), key=lambda s: Path(s).name):
        s = cov_data["files"][fname]["summary"]
        print("%-28s %9d %10d %7.1f%%" % (Path(fname).name,
                                           s["num_statements"],
                                           s["covered_lines"],
                                           s["percent_covered"]))
    print("-" * 72)
    t = cov_data["totals"]
    print("%-28s %9d %10d %7.1f%%" % ("TOTAL",
                                       t["num_statements"],
                                       t["covered_lines"],
                                       t["percent_covered"]))


def _print_targets(cov_data, min_pct):
    print()
    print("=" * 72)
    print("ПОКРЫТИЕ ЦЕЛЕВЫХ ФУНКЦИЙ (правки #1-#7, U1-U2)")
    print("=" * 72)
    for fname, funcs in TARGETS.items():
        info = _file_info(cov_data, fname)
        if info is None:
            print("\n[%s] — нет данных (модуль не импортировался)" % fname)
            continue
        executed = set(info.get("executed_lines") or [])
        missing = set(info.get("missing_lines") or [])
        func_ranges = _find_functions(ROOT / fname)
        print("\n[%s]" % fname)
        print("-" * 72)
        for name, desc in funcs:
            ranges = func_ranges.get(name)
            if not ranges:
                print("  ?  %-36s  (не найдена)" % name)
                continue
            st = _func_stats(ranges, executed, missing)
            pct = st["percent"]
            if st["total"] == 0:
                mark = "?"
            elif pct >= min_pct:
                mark = "✓"
            elif pct > 0:
                mark = "~"
            else:
                mark = "✗"
            print("  %s  %-36s %5.1f%%  (%3d/%-3d)  %s"
                  % (mark, name, pct, st["executed"], st["total"], desc))


def _print_legend(min_pct):
    print()
    print("-" * 72)
    print("Легенда:  ✓ ≥ %d%%   ~ 1..%d%%   ✗ 0%%   ? нет строк"
          % (int(min_pct), int(min_pct) - 1))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-html", action="store_true")
    ap.add_argument("--no-run", action="store_true")
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--min", type=float, default=60.0)
    ap.add_argument("--targets", nargs="*", default=["app"])
    ap.add_argument("--python", default=None)
    args = ap.parse_args()

    if not args.no_run:
        py = _pick_python(args.python)
        if py is None:
            return 2
        _run_pytest(py, args.targets, html=not args.no_html)

    cov = _load_cov()
    if cov is None:
        print("\nПроверь вывод pytest выше.")
        return 1

    _print_overall(cov)
    _print_targets(cov, args.min)
    _print_legend(args.min)

    print()
    print("HTML: %s" % (HTML_DIR / "index.html"))
    print("JSON: %s" % COV_JSON)

    if args.open:
        idx = HTML_DIR / "index.html"
        if idx.exists():
            webbrowser.open(idx.as_uri())
        else:
            print("! %s нет" % idx)
    return 0


if __name__ == "__main__":
    sys.exit(main())