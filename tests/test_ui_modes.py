"""Тесты для режимов интерфейса (Простой / Экспертный)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_expert_only_buttons_have_attribute():
    """Проверяет, что нужные кнопки помечены data-expert-only."""
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    expert_only_ids = [
        "samBtn", "freezeBtn", "streamsBtn", "trackMgmtBtn", "webhooksBtn",
        "attrAuditBehBtn", "attrBlurBtn", "attrClearBlurBtn", "attrValidateBehBtn",
    ]

    for btn_id in expert_only_ids:
        # Ищем кнопку с этим ID и проверяем наличие атрибута
        assert f'id="{btn_id}"' in html, f"Кнопка {btn_id} не найдена"
        # Простая эвристика: ищем тег button, содержащий id
        import re
        match = re.search(rf'<button[^>]*id="{btn_id}"[^>]*>', html)
        assert match, f"Не найден тег button для {btn_id}"
        assert 'data-expert-only="true"' in match.group(0), \
            f"Кнопка {btn_id} не имеет data-expert-only"

    # Отдельно — кнопка ⚡ (без ID, только data-action)
    import re
    match = re.search(r'<button[^>]*data-action="runAsyncAutolabel"[^>]*>', html)
    assert match, "Не найден тег button для runAsyncAutolabel"
    assert 'data-expert-only="true"' in match.group(0), \
        "Кнопка runAsyncAutolabel не имеет data-expert-only"


def test_ui_mode_css_exists():
    """Проверяет, что CSS скрывает экспертные элементы."""
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    assert 'html[data-ui-mode="simple"] [data-expert-only="true"]' in css, \
        "CSS-правило для скрытия экспертных элементов отсутствует"


def test_ui_mode_js_functions_exist():
    """Проверяет, что в main.js есть логика переключения."""
    js = (ROOT / "js" / "main.js").read_text(encoding="utf-8")
    assert "function getUIMode()" in js
    assert "function applyUIMode()" in js
    assert "function setUIMode(mode)" in js
