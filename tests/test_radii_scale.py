"""Patcher 1 — radii tokens (DS-01)."""
import re
from pathlib import Path


def test_border_radius_uses_tokens():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    declarations = re.findall(r"border-radius:\s*([^;]+);", css)
    violations = []
    for decl in declarations:
        val = decl.replace("!important", "").strip()
        for part in val.split():
            if part in ("0", "inherit", "50%", "auto"):
                continue
            if "var(--radius-" in part:
                continue
            if re.match(r"^\d+(?:\.\d+)?px$", part):
                violations.append(part)
    assert not violations, (
        f"Hardcoded border-radius без var(--radius-*): {sorted(set(violations))}"
    )


def test_radii_tokens_present():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    for tok, val in (("--radius-window", "12px"), ("--radius-panel", "10px"),
                     ("--radius-control", "8px"), ("--radius-pill", "999px")):
        assert f"{tok}: {val}" in css, f"{tok}: {val} не найден"


def test_legacy_radii_removed():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    for legacy in ("--radius-xs:", "--radius-sm:", "--radius-md:",
                   "--radius-lg:", "--radius-xl:"):
        assert legacy not in css, f"legacy-токен {legacy} должен быть удалён"
