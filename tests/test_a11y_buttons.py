"""[STAGE4:E4-ARIA] dev-panel buttons have aria-label."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "js" / "main.js"


def test_dev_panel_buttons_have_aria_label():
    src = MAIN.read_text(encoding="utf-8")
    idx = src.find("function _startDevPanel(")
    assert idx >= 0, "_startDevPanel not found"
    end = src.find("\nfunction ", idx + 1)
    if end < 0:
        end = len(src)
    body = src[idx:end]
    assert "aria-label" in body
    assert "btnCurl.setAttribute('aria-label'" in body, \
        "btnCurl aria-label not set"
    assert "btnClose.setAttribute('aria-label'" in body, \
        "btnClose aria-label not set"
