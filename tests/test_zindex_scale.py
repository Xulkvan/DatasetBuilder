"""Patcher 1 — z-index scale (F-04)."""
import re
from pathlib import Path

_ALLOWED = {"0", "10", "20", "50", "100", "200", "1000", "1001", "2000", "3000", "4000"}


def test_zindex_uses_tokens():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    matches = re.findall(r"z-index:\s*(\d+)\s*(?:!important)?\s*;", css)
    violations = [m for m in matches if int(m) >= 10 and m not in _ALLOWED]
    assert not violations, f"z-index вне токенов --z-*: {sorted(set(violations))}"


def test_zindex_tokens_defined():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    for tok in ("--z-toolbar", "--z-status", "--z-resizer",
                "--z-popover", "--z-overlay", "--z-modal",
                "--z-toast", "--z-tour", "--z-dev"):
        assert tok + ":" in css, f"{tok} не определён в :root"
