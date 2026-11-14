"""[Patcher 9] Q8=C: reviewActionsGroup visible only for reviewer/admin.

- index.html: #reviewActionsGroup без inline display:none.
- data-requires="annotation.review" на всех трёх кнопках (submit/approve/reject).
- js/main.js::_applyAuthVisibility устанавливает display для группы по роли.
- js/main.js::_refreshAttrBar пересчитывает при смене кадра.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"
MAIN = ROOT / "js" / "main.js"


def test_review_group_has_no_display_none():
    html = HTML.read_text(encoding="utf-8")
    m = re.search(r'<div[^>]*id="reviewActionsGroup"[^>]*>', html)
    assert m, "#reviewActionsGroup not found in index.html"
    assert "display:none" not in m.group(0), (
        "#reviewActionsGroup must not have inline display:none"
    )


def test_review_buttons_require_review_permission():
    html = HTML.read_text(encoding="utf-8")
    for btn_id in ("attrSubmitReviewBtn", "attrApproveBtn", "attrRejectBtn"):
        m = re.search(r'<button[^>]*id="' + btn_id + r'"[^>]*>', html)
        assert m, f"button #{btn_id} not found"
        assert 'data-requires="annotation.review"' in m.group(0), (
            f"#{btn_id} must have data-requires=\"annotation.review\""
        )


def test_apply_auth_visibility_handles_review_group():
    src = MAIN.read_text(encoding="utf-8")
    assert "reviewActionsGroup" in src, (
        "main.js does not reference reviewActionsGroup"
    )
    assert "reviewer" in src, "main.js does not check for 'reviewer' role"
    idx = src.find("reviewActionsGroup")
    assert idx >= 0
    tail = src[idx:idx + 800]
    assert "'flex'" in tail or '"flex"' in tail, (
        "_applyAuthVisibility должен ставить display='flex' для review-группы"
    )


def test_refresh_attr_bar_calls_auth_visibility():
    src = MAIN.read_text(encoding="utf-8")
    idx = src.find("function _refreshAttrBar(")
    assert idx >= 0, "_refreshAttrBar not found"
    end = src.find("\nfunction ", idx + 1)
    if end < 0:
        end = len(src)
    body = src[idx:end]
    assert "_applyAuthVisibility" in body, (
        "_refreshAttrBar не вызывает _applyAuthVisibility — "
        "видимость review-actions не обновится при смене кадра"
    )
