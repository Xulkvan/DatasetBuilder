#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_coverage.py — coverage-отчёт по целевым функциям DatasetBuilder.
Обновлен под новую архитектуру (роутеры + сервисы) и кроссплатформенные пути.
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

# Обновленные таргеты под новую структуру файлов
TARGETS = {
    "routers/images.py": [
        ("get_annotations", "#1 order_by(Annotation.id)"),
        ("save_annotations", "#4 upsert: keypoints, annotation_id stable"),
    ],
    "app.py": [
        ("backup_project", "#2 backup: keypoints+attrs"),
        ("copy_annotations", "#3 copy: чистка kp + attrs"),
        ("_bulk_transfer", "#5 bulk copy: kp+attrs"),
        ("_process_dataset_zip", "U1 import cancel"),
        ("import_cancel", "U2 /api/import/cancel"),
        ("health_check", "[STAGE5] /api/health"),
        ("add_request_id", "[STAGE5] X-Request-ID middleware"),
    ],
    "services/ml_service.py": [
        ("_apply_pose_detection_to_anns", "#4 pose autolabel replace-safe"),
    ],
    "services/behavior_service.py": [
        ("predict_behavior_from_keypoints", "ref: поведение по скелету"),
    ],
    "services/image_service.py": [
        ("_iou_xywh", "ref: IoU"),
        ("_hex_to_int", "ref: pHash"),
    ],
    "config.py": [
        ("_norm_behavior", "ref: поведение"),
    ]
}


def _venv_bins(base: Path) -> list:
    if os.name == "nt":
        return [base / ".venv" / "Scripts" / "python.exe",
                base / "venv" / "Scripts" / "python.exe"]
    return [base / ".venv" / "bin" / "python",
            base / "venv" / "bin" / "python"]


def _candidate_pythons(explicit):
    out = []
    if explicit: out.append(Path(explicit))
    for base in (ROOT, ROOT.parent, ROOT.parent.parent):
        out.extend(_venv_bins(base))
    venv = os.environ.get("VIRTUAL_ENV")
    if venv: out.extend(_venv_bins(Path(venv)))
    if sys.executable: out.append(Path(sys.executable))

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


_PROBE = "\n".join([
    "import sys",
    "mods = ['pytest', 'pytest_cov', 'fastapi', 'uvicorn']",
    "missing = []",
    "for m in mods:",
    "    try: __import__(m)",
    "    except Exception: missing.append(m)",
    "print('|'.join(missing))",
    "sys.exit(0 if not missing else 1)",
])


def _probe_python(py: Path):
    if not py.exists(): return False, "не найден"
    try:
        r = subprocess.run([str(py), "-c", _PROBE], capture_output=True, text=True, timeout=30)
    except Exception as e:
        return False, "не запускается: %s" % e
    if r.returncode == 0: return True, ""
    missing = (r.stdout or "").strip().replace("|", ", ")
    return False, "нет модулей: " + missing


def _pick_python(explicit):
    print("Поиск Python с зависимостями проекта:")
    for py in _candidate_pythons(explicit):
        ok, reason = _probe_python(py)
        print(f"  [{'✓' if ok else '✗'}] {py}" + ("" if ok else f"  — {reason}"))
        if ok: return py
    print("\nНи один интерпретатор не подошёл.")
    return None


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


def _run_pytest(py: Path, html: bool) -> int:
    cmd = [str(py), "-m", "pytest", "tests/", "--cov=app", "--cov=services", "--cov=routers"]
    cmd.append("--cov-report=json:" + COV_JSON.name)
    if html: cmd.append("--cov-report=html:" + HTML_DIR.name)
    cmd.append("-q")

    print(f"\n$ {' '.join(cmd)}\n")
    t0 = time.time()
    r = subprocess.run(cmd, cwd=str(ROOT))
    print("\n[pytest: %.1fs, exit=%d]" % (time.time() - t0, r.returncode))
    return r.returncode


def _load_cov():
    if not COV_JSON.exists(): return None
    try:
        return json.loads(COV_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None


def _file_info(cov_data, rel_fname):
    # ФИКС ДЛЯ WINDOWS: нормализуем слэши, чтобы "services\ml.py" == "services/ml.py"
    target = rel_fname.replace("\\", "/")
    for k, info in cov_data["files"].items():
        if k.replace("\\", "/").endswith(target):
            return info
    return None


def _print_overall(cov_data):
    print("=" * 72)
    print("ОБЩЕЕ ПОКРЫТИЕ")
    print("=" * 72)
    print("%-28s %9s %10s %8s" % ("Файл", "Строк", "Покрыто", "%"))
    print("-" * 72)

    files = sorted(cov_data["files"].keys(), key=lambda s: Path(s).name)
    for fname in files:
        s = cov_data["files"][fname]["summary"]
        print("%-28s %9d %10d %7.1f%%" % (Path(fname).name, s["num_statements"], s["covered_lines"],
                                          s["percent_covered"]))

    print("-" * 72)
    t = cov_data["totals"]
    print("%-28s %9d %10d %7.1f%%" % ("TOTAL", t["num_statements"], t["covered_lines"], t["percent_covered"]))


def _print_targets(cov_data, min_pct):
    print("\n" + "=" * 72)
    print("ПОКРЫТИЕ ЦЕЛЕВЫХ ФУНКЦИЙ (правки #1-#7, U1-U2, Stage 5)")
    print("=" * 72)

    for rel_fname, funcs in TARGETS.items():
        info = _file_info(cov_data, rel_fname)
        print(f"\n[{rel_fname}]")
        print("-" * 72)
        if info is None:
            print("  ?  (файл не найден в отчете покрытия)")
            continue

        executed = set(info.get("executed_lines") or [])
        missing = set(info.get("missing_lines") or [])
        func_ranges = _find_functions(ROOT / rel_fname)

        for name, desc in funcs:
            ranges = func_ranges.get(name)
            if not ranges:
                print(f"  ?  {name:<36}  (не найдена в файле)")
                continue
            st = _func_stats(ranges, executed, missing)
            pct = st["percent"]
            mark = "✓" if st["total"] > 0 and pct >= min_pct else (
                "~" if st["total"] > 0 and pct > 0 else ("?" if st["total"] == 0 else "✗"))
            print(f"  {mark}  {name:<36} {pct:5.1f}%  ({st['executed']:3d}/{st['total']:<3d})  {desc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-html", action="store_true")
    ap.add_argument("--no-run", action="store_true")
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--min", type=float, default=60.0)
    ap.add_argument("--python", default=None)
    args = ap.parse_args()

    if not args.no_run:
        py = _pick_python(args.python)
        if py is None: return 2
        _run_pytest(py, html=not args.no_html)

    cov = _load_cov()
    if cov is None:
        print("\n✗ coverage.json не создан — coverage не собрался.")
        return 1

    _print_overall(cov)
    _print_targets(cov, args.min)

    print("\nHTML: %s" % (HTML_DIR / "index.html"))
    if args.open and (HTML_DIR / "index.html").exists():
        webbrowser.open((HTML_DIR / "index.html").as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
