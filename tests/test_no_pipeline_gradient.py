"""Patcher 3 — no gradient on #pipelineBtn (F-17).

До Patcher 3 кнопка имела inline `linear-gradient(135deg, #0071e3, #34c759)`
— два accent одновременно, что противоречит Apple HIG (один primary accent).
После: solid `--accent`, `data-celebrate="1"` → `--success` на 2s после done.
"""
import re
from pathlib import Path


def test_pipeline_btn_no_gradient():
    html = (Path(__file__).parent.parent / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<button[^>]*id="pipelineBtn"[^>]*>', html)
    assert m, "pipelineBtn start tag not found in index.html"
    start_tag = m.group(0)
    assert "linear-gradient" not in start_tag, (
        f"pipelineBtn has inline gradient: {start_tag[:200]}"
    )
    assert "135deg" not in start_tag, (
        f"pipelineBtn has 135deg gradient angle: {start_tag[:200]}"
    )


def test_pipeline_btn_no_global_blue_green_gradient():
    html = (Path(__file__).parent.parent / "index.html").read_text(encoding="utf-8")
    assert not re.search(
        r"linear-gradient\s*\(\s*135deg\s*,\s*#0071e3", html, re.IGNORECASE
    ), "Found 135deg #0071e3 gradient — likely pipelineBtn"


def test_celebrate_css_rule_exists():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    assert '.btn-primary[data-celebrate="1"]' in css, (
        "Missing .btn-primary[data-celebrate='1'] rule — celebrate state not styled"
    )
    assert "var(--success)" in css.split('.btn-primary[data-celebrate="1"]')[1][:200], (
        "celebrate state должен использовать var(--success)"
    )
