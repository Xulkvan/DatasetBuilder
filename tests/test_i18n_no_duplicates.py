"""[STAGE6:i18n-dedupe] i18n.js keys must be unique and semantic.

Проверяет:
  * нет дубликатов ключей в ru-блоке;
  * нет дубликатов ключей в en-блоке;
  * не осталось hash-ключей (msg_xxxxxx, msg.xxx);
  * все ключи семантические (domain.action.state).
"""
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N_PATH = ROOT / "i18n.js"


def _extract_locale_block(text: str, locale: str) -> str:
    marker = "\n  " + locale + ": {"
    start = text.find(marker)
    assert start >= 0, locale + " block not found in i18n.js"
    start += len(marker)
    depth = 1
    i = start
    in_str = None
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ('"', "'", "`"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i]
        i += 1
    raise AssertionError(locale + " block not closed")


def _keys_in_block(block: str) -> list:
    return re.findall(r"'([a-zA-Z][\w.]*)'\s*:", block)


def test_no_duplicate_keys_ru():
    text = I18N_PATH.read_text(encoding="utf-8")
    ru = _extract_locale_block(text, "ru")
    keys = _keys_in_block(ru)
    assert keys, "no keys found in ru block"
    dups = {k: v for k, v in Counter(keys).items() if v > 1}
    assert not dups, "duplicate ru keys: " + str(dups)


def test_no_duplicate_keys_en():
    text = I18N_PATH.read_text(encoding="utf-8")
    en = _extract_locale_block(text, "en")
    keys = _keys_in_block(en)
    assert keys, "no keys found in en block"
    dups = {k: v for k, v in Counter(keys).items() if v > 1}
    assert not dups, "duplicate en keys: " + str(dups)


def test_no_hash_keys():
    text = I18N_PATH.read_text(encoding="utf-8")
    ru = _extract_locale_block(text, "ru")
    bad = [k for k in _keys_in_block(ru) if re.match(r"^msg[._]", k)]
    assert not bad, "msg_* hash-keys still present: " + str(bad[:10])


def test_keys_are_semantic():
    text = I18N_PATH.read_text(encoding="utf-8")
    ru = _extract_locale_block(text, "ru")
    keys = _keys_in_block(ru)
    bad = [k for k in keys if "." not in k]
    assert not bad, "non-semantic keys (no dots): " + str(bad[:10])
