"""[STAGE6] XSS-регрессии в JS-модулях (статические проверки)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_unescaped_emessage_in_innerhtml():
    """`innerHTML = ... e.message` без escapeHtml — потенциальный XSS."""
    src = (ROOT / "js" / "main.js").read_text(encoding="utf-8")
    lines = src.splitlines()
    bad = []
    for i, line in enumerate(lines):
        if "innerHTML" not in line:
            continue
        window = "\n".join(lines[max(0, i - 2): i + 4])
        if "e.message" in window and "escapeHtml" not in window:
            bad.append((i + 1, line.strip()[:80]))
    assert not bad, f"unescaped e.message in innerHTML: {bad}"


def test_escapehtml_handles_all_five_chars():
    """Утилита escapeHtml должна покрывать & < > " '."""
    src = (ROOT / "js" / "utils.js").read_text(encoding="utf-8")
    for ch in ["&amp;", "&lt;", "&gt;", "&quot;", "&#39;"]:
        assert ch in src, f"{ch} missing in escapeHtml"


def test_no_known_unescaped_dynamic_innerhtml():
    """Список известных проблемных мест должен быть пуст."""
    src = (ROOT / "js" / "main.js").read_text(encoding="utf-8")
    patterns = [
        r"wh\.event_type\s*\+",
        r"textEl\.innerHTML\s*=\s*t\(",
    ]
    for pat in patterns:
        assert not re.search(pat, src), f"unescaped pattern: {pat}"


def test_trustedhtml_used_in_setstatus():
    """Все вызовы setStatus должны использовать trustedHtml, не html."""
    src = (ROOT / "js" / "main.js").read_text(encoding="utf-8")
    # В теле функции должно быть ровно одно `!!opts.trustedHtml`
    assert src.count("!!opts.trustedHtml") >= 1, \
        "setStatus не использует opts.trustedHtml"
    # html: true допустим только в комментариях/строках —
    # ищем именно как объектный литерал в вызовах setStatus
    assert ", { html: true })" not in src, \
        "найден вызов setStatus(..., { html: true }) — переименуйте в trustedHtml"

# Stage 5.7 — no-DOMPurify fallback in setStatus
def test_setstatus_no_dompurify_fallback_to_text():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "js" / "main.js").read_text(
        encoding="utf-8")
    # Проверяем, что в fallback используется textContent, а не innerHTML
    assert "el.textContent = String(msg);" in src
    assert "el.innerHTML = String(msg);" not in src
