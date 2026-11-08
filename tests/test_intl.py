"""[STAGE4:E4-INTL] Intl helpers exported & used."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UTILS = ROOT / "js" / "utils.js"
MAIN = ROOT / "js" / "main.js"


def test_intl_helpers_exported():
    src = UTILS.read_text(encoding="utf-8")
    assert "export function fmtDate" in src
    assert "export function fmtNumber" in src
    assert "Intl.DateTimeFormat" in src
    assert "Intl.NumberFormat" in src


def test_intl_helpers_imported_in_main():
    src = MAIN.read_text(encoding="utf-8")
    idx = src.find("from './utils.js'")
    assert idx >= 0
    ctx = src[max(0, idx - 500):idx]
    assert "fmtDate" in ctx
    assert "fmtNumber" in ctx
