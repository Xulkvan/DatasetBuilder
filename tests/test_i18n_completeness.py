# tests/test_i18n_completeness.py
"""Регрессия: каждый ключ RU должен иметь EN-пару.

Иначе EN-пользователь видит fallback на русский (или сам ключ,
если fallback отсутствует).
"""
import re
from pathlib import Path


def _extract_keys(block: str) -> set[str]:
    return set(re.findall(r"['\"]([a-zA-Z][\w.]*)['\"]\s*:", block))


def test_all_ru_keys_have_en():
    text = (Path(__file__).parent.parent / "i18n.js").read_text(encoding="utf-8")
    en_idx = text.find("\n  en: {")
    assert en_idx > 0, "en: block missing"
    ru_block = text[:en_idx]
    en_block = text[en_idx:]

    ru_keys = _extract_keys(ru_block)
    en_keys = _extract_keys(en_block)
    missing = ru_keys - en_keys

    assert not missing, (
        f"Keys present in RU but missing in EN ({len(missing)}): "
        f"{sorted(missing)[:20]}"
    )
