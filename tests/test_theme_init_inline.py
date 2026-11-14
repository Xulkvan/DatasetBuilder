"""Patcher 1 — FOUC (F-09): inline theme-init."""
from pathlib import Path


def _head(html: str) -> str:
    start = html.find("<head>")
    end = html.find("</head>")
    assert start >= 0 and end > start, "index.html: <head> not found"
    return html[start:end]


def test_no_module_theme_init():
    html = (Path(__file__).parent.parent / "index.html").read_text(encoding="utf-8")
    assert '<script type="module" src="/js/theme-init.js">' not in html


def test_no_data_theme_in_html_attr():
    html = (Path(__file__).parent.parent / "index.html").read_text(encoding="utf-8")
    assert 'data-theme="light"' not in html
    assert 'data-theme="dark"' not in html


def test_inline_theme_script_in_head_before_stylesheet():
    html = (Path(__file__).parent.parent / "index.html").read_text(encoding="utf-8")
    head = _head(html)
    inline = head.find("localStorage.getItem('pdb_theme')")
    stylesheet = head.find('<link rel="stylesheet"')
    assert inline > 0, "inline-инициализация темы отсутствует в <head>"
    assert stylesheet > 0, "stylesheet link отсутствует в <head>"
    assert inline < stylesheet, (
        "inline-script темы ДОЛЖЕН идти ДО <link rel=stylesheet>, иначе FOUC"
    )


def test_theme_init_file_deleted():
    theme_init = Path(__file__).parent.parent / "js" / "theme-init.js"
    assert not theme_init.exists()
