"""Stage 7: zoom controls — круглые Liquid Glass floating-кнопки."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "style.css").read_text(encoding="utf-8")


def _zoom_button_body() -> str:
    m = re.search(r"\.zoom-controls button\s*\{([^}]*)\}", CSS)
    assert m, ".zoom-controls button rule not found"
    return m.group(1)


def test_zoom_button_is_round():
    assert "border-radius: 50%" in _zoom_button_body(), \
        "кнопки зума должны быть круглыми (border-radius: 50%)"


def test_zoom_button_uses_glass_tokens():
    body = _zoom_button_body()
    assert "var(--glass-bg)" in body, "кнопки зума должны использовать --glass-bg"
    assert "backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate))" in body, \
        "кнопки зума должны использовать --glass-blur/--glass-saturate"


def test_zoom_button_fallbacks():
    sup = re.search(
        r"@supports\s+not\s+\(\(backdrop-filter:.*?\)\)\s*\{(.*?)\n\}", CSS, re.DOTALL
    )
    assert sup, "@supports fallback not found"
    assert ".zoom-controls button" in sup.group(1), \
        ".zoom-controls button отсутствует в @supports fallback"

    rt = re.search(
        r"@media\s*\(prefers-reduced-transparency:\s*reduce\)\s*\{(.*?)\n\}",
        CSS, re.DOTALL,
    )
    assert rt, "prefers-reduced-transparency block not found"
    assert ".zoom-controls button" in rt.group(1), \
        ".zoom-controls button отсутствует в prefers-reduced-transparency"
