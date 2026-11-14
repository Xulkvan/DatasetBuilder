"""Patcher 6 — A11y listbox (A11Y-01/02, F-14, F-15).

Регрессия: keyboard/VoiceOver-навигация по списку проектов и изображений
через roving tabindex, role="listbox"/"option"/"menuitem".

Проверяет:
  * js/a11y_listbox.js существует и экспортирует installRovingTabindex;
  * в js/main.js installRovingTabindex импортируется и вызывается для
    #projects и #imageList;
  * section-row имеет role="presentation";
  * меню (#sortMenu, #exportMenu, #bulkTagMenu, #fileOpsMenu) содержат
    role="menuitem".
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "js"


def test_a11y_listbox_module_exists():
    p = JS / "a11y_listbox.js"
    assert p.exists(), "js/a11y_listbox.js не создан — Patcher 6 не применён"


def test_a11y_listbox_exports_helper():
    src = (JS / "a11y_listbox.js").read_text(encoding="utf-8")
    assert "export function installRovingTabindex" in src
    assert "ArrowDown" in src
    assert "ArrowUp" in src
    assert "aria-selected" in src


def test_main_imports_helper():
    src = (JS / "main.js").read_text(encoding="utf-8")
    assert "from './a11y_listbox.js'" in src, \
        "main.js не импортирует installRovingTabindex"


def test_main_installs_roving_for_projects():
    src = (JS / "main.js").read_text(encoding="utf-8")
    assert "installRovingTabindex(document.getElementById('projects')" in src, \
        "installRovingTabindex для #projects не вызван"


def test_main_installs_roving_for_image_list():
    src = (JS / "main.js").read_text(encoding="utf-8")
    assert "installRovingTabindex(inner" in src, \
        "installRovingTabindex для #imageListInner не вызван"


def test_section_row_is_presentation():
    src = (JS / "main.js").read_text(encoding="utf-8")
    assert "row.setAttribute('role', 'presentation')" in src, \
        "section-row должна иметь role='presentation'"


def test_make_main_row_sets_tabindex():
    src = (JS / "main.js").read_text(encoding="utf-8")
    assert "row.tabIndex = -1" in src
    assert "aria-selected" in src


def test_menus_have_menuitem_role():
    """В js/main.js для меню добавляется role='menuitem'."""
    src = (JS / "main.js").read_text(encoding="utf-8")
    assert "role', 'menuitem'" in src or 'role="menuitem"' in src, \
        "role='menuitem' не устанавливается на пункты меню"
