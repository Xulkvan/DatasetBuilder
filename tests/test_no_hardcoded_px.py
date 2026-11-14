"""Patcher 1 — no hardcoded font-size / duration (PERF-02, F-18)."""
import re
from pathlib import Path


def test_no_hardcoded_font_size():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    for bad in ("0.75rem", "0.8125rem", "0.6875rem"):
        pat = re.compile(r"font-size:\s*" + re.escape(bad) + r"\s*;")
        assert not pat.search(css), (
            f"hardcoded font-size: {bad} — должен быть через var(--fs-*)"
        )


def test_legacy_duration_tokens_removed():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    for legacy in ("--dur-instant:", "--dur-normal:", "--dur-lift:", "--dur-slow:"):
        assert legacy not in css, f"legacy duration-токен {legacy} остался"
    for legacy_use in ("var(--dur-instant)", "var(--dur-normal)",
                       "var(--dur-lift)", "var(--dur-slow)"):
        assert legacy_use not in css


def test_new_duration_tokens_present():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    assert "--dur-fast: 120ms" in css
    assert "--dur-base: 220ms" in css
    assert "--dur-emphasized: 300ms" in css
