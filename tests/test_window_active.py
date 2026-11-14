"""Patcher 2 — active-window emulation (Q2/Q1=B).

`data-window-active` на <html>; модуль js/window_chrome.js
обновляет его по focus/blur. Materials притухают при `=false`.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_window_chrome_js_exists():
    p = ROOT / "js" / "window_chrome.js"
    assert p.exists(), "js/window_chrome.js не создан — Q2 не применён"


def test_window_active_js_present():
    """В js/window_chrome.js есть document.hasFocus и dataset.windowActive."""
    src = (ROOT / "js" / "window_chrome.js").read_text(encoding="utf-8")
    assert "document.hasFocus" in src, (
        "document.hasFocus отсутствует в js/window_chrome.js"
    )
    assert (
        "windowActive" in src
        or "data-window-active" in src
    ), "data-window-active не выставляется из js/window_chrome.js"
    assert "installWindowChrome" in src, (
        "installWindowChrome не экспортируется — main.js не сможет вызвать"
    )


def test_index_html_has_default_false():
    """<html ... data-window-active="false"> — default до первого focus."""
    src = (ROOT / "index.html").read_text(encoding="utf-8")
    m = re.search(r"<html\b[^>]*>", src)
    assert m, "<html> тег не найден"
    tag = m.group(0)
    assert 'data-window-active="false"' in tag, (
        f"<html> должен иметь data-window-active='false' по умолчанию; "
        f"получено: {tag[:200]}"
    )


def test_main_js_calls_install_window_chrome():
    src = (ROOT / "js" / "main.js").read_text(encoding="utf-8")
    assert "from './window_chrome.js'" in src, (
        "js/main.js не импортирует ./window_chrome.js"
    )
    assert "installWindowChrome(" in src, (
        "js/main.js не вызывает installWindowChrome()"
    )


def test_style_css_dims_inactive():
    """При data-window-active=false — saturate(0.94)."""
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    assert 'data-window-active="false"' in css, (
        "style.css не содержит правил для data-window-active"
    )
    assert "saturate(0.94)" in css, (
        "saturate(0.94) отсутствует — материалы не притухают"
    )
