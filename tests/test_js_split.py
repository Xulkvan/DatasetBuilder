"""[STAGE8_CODE_HYGIENE] Regression: js/file_ops.js extracted from main.js.

Проверяет, что file-ops функции вынесены в отдельный модуль, экспортируются,
и что main.js импортирует их оттуда (а не определяет заново).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE_OPS = ROOT / "js" / "file_ops.js"
MAIN_JS = ROOT / "js" / "main.js"


def test_file_ops_js_exists():
    assert FILE_OPS.exists(), (
        "js/file_ops.js не создан — STAGE8 не применился"
    )


def test_file_ops_exports_functions():
    src = FILE_OPS.read_text(encoding="utf-8")
    for fn in (
        "openBulkRename", "openMoveCopyDialog", "openDuplicatesModal",
        "toggleFileOpsMenu", "downloadFilesCsv", "downloadBoxesCsv",
    ):
        assert f"export async function {fn}" in src or \
               f"export function {fn}" in src, (
            f"js/file_ops.js не экспортирует {fn}"
        )


def test_file_ops_binds_window():
    src = FILE_OPS.read_text(encoding="utf-8")
    for fn in (
        "openBulkRename", "openMoveCopyDialog", "openDuplicatesModal",
        "toggleFileOpsMenu", "downloadFilesCsv", "downloadBoxesCsv",
    ):
        assert f"window.{fn} =" in src, (
            f"js/file_ops.js должен вешать window.{fn} для data-action в HTML"
        )


def test_main_js_imports_from_file_ops():
    src = MAIN_JS.read_text(encoding="utf-8")
    assert "from './file_ops.js'" in src, (
        "js/main.js не импортирует из ./file_ops.js — STAGE8 не применился"
    )


def test_main_js_no_longer_defines_moved_functions():
    src = MAIN_JS.read_text(encoding="utf-8")
    for fn in (
        "openBulkRename", "openMoveCopyDialog", "openDuplicatesModal",
        "toggleFileOpsMenu", "downloadFilesCsv", "downloadBoxesCsv",
    ):
        # Ищем «живое» определение (не в импорте)
        marker_async = f"async function {fn}("
        marker_sync = f"function {fn}("
        # Если есть `async function fn(` или `function fn(` — плохо
        # (но игнорируем если это часть window.xxx = ...)
        import re
        # `function fn(` как отдельный токен
        pat = re.compile(rf"^\s*(async\s+)?function\s+{re.escape(fn)}\s*\(",
                         re.MULTILINE)
        assert not pat.search(src), (
            f"js/main.js всё ещё определяет function {fn}( — "
            f"функция должна быть в file_ops.js"
        )
