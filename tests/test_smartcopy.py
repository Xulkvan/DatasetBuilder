"""[STAGE4:E4-SMARTCOPY] dialog state corruption must be fixed."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "js" / "main.js"
INDEX = ROOT / "index.html"


def test_custom_actions_container_in_html():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="dialogCustomActions"' in html, \
        "#dialogCustomActions container missing in index.html"


def test_smartcopy_no_innerHTML_clear():
    src = MAIN.read_text(encoding="utf-8")
    idx = src.find("function _showSmartCopyCaseCDialog(")
    assert idx >= 0, "_showSmartCopyCaseCDialog not found"
    end = src.find("\nfunction ", idx + 100)
    if end < 0:
        end = len(src)
    body = src[idx:end]
    assert "actionsRow.innerHTML = ''" not in body, \
        "old actionsRow.innerHTML = '' still present (state corruption)"
    assert "dialogCustomActions" in body, \
        "customActions container not used"
    assert "MutationObserver" in body, \
        "backdrop-close observer missing"


def test_smartcopy_does_not_remove_default_buttons():
    src = MAIN.read_text(encoding="utf-8")
    idx = src.find("function _showSmartCopyCaseCDialog(")
    end = src.find("\nfunction ", idx + 100)
    if end < 0:
        end = len(src)
    body = src[idx:end]
    assert "actionsRow.innerHTML = ''" not in body
    assert "customActions.appendChild(btnReplaceAll)" in body
