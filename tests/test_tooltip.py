"""[STAGE4:E4-TOOLTIP] data-tooltip in index.html."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"


def test_icon_btns_have_data_tooltip():
    html = INDEX.read_text(encoding="utf-8")
    for m in re.finditer(
        r'<button\b[^>]*\bclass="[^"]*\bicon-btn\b[^"]*"[^>]*>', html
    ):
        btn = m.group(0)
        assert ("data-tooltip=" in btn or "data-i18n-tooltip=" in btn), \
            f"icon-btn without data-tooltip: {btn[:150]}"


def test_no_title_without_data_tooltip():
    """После патча ни у одного элемента не должно остаться title= без data-tooltip."""
    html = INDEX.read_text(encoding="utf-8")
    for m in re.finditer(r'<[a-zA-Z][^>]*\btitle="[^"]*"[^>]*>', html):
        tag = m.group(0)
        assert "data-tooltip=" in tag, \
            f"title= without data-tooltip: {tag[:150]}"
