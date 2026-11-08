"""[STAGE4:E4-I18N-DUP] no RU duplicates in en: locale."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N_PATH = ROOT / "i18n.js"


def _extract_en_section(text):
    m = re.search(r"\n  en: \{", text)
    assert m, "en: section not found"
    start = m.end()
    depth = 1
    i = start
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    raise AssertionError("en: section has no closing brace")


_DUP_RU = [
    ("versions.diff.keypoints_added", "Точек скелета добавлено"),
    ("versions.diff.keypoints_removed", "Точек скелета удалено"),
    ("versions.diff.behaviors_added", "Поведений размечено"),
    ("versions.diff.behaviors_removed", "Поведений удалено"),
]


def test_no_russian_versions_diff_in_en():
    text = I18N_PATH.read_text(encoding="utf-8")
    en = _extract_en_section(text)
    offenders = []
    for key, ru_val in _DUP_RU:
        pat = f"'{key}': '{ru_val}'"
        if pat in en:
            offenders.append(pat)
    assert not offenders, (
        "Russian versions.diff.* duplicates in en: locale:\n"
        + "\n".join(offenders)
    )


def test_english_versions_diff_present():
    text = I18N_PATH.read_text(encoding="utf-8")
    en = _extract_en_section(text)
    assert "'versions.diff.keypoints_added': 'Keypoints added'" in en
    assert "'versions.diff.behaviors_added': 'Behaviors labeled'" in en
