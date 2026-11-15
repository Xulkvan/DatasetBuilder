"""Stage 6: trash drop-target — изображения и проекты перетаскиваются в корзину."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "style.css").read_text(encoding="utf-8")
MAIN = (ROOT / "js" / "main.js").read_text(encoding="utf-8")


def test_trash_sprite_has_closed_and_open_symbols():
    assert 'id="i-trash-closed"' in HTML, "SVG-символ i-trash-closed отсутствует"
    assert 'id="i-trash-open"' in HTML, "SVG-символ i-trash-open отсутствует"


def test_trash_button_has_two_icon_layers():
    m = re.search(r'<button[^>]*id="trashToggleBtn"[^>]*>(.*?)</button>', HTML, re.DOTALL)
    assert m, "#trashToggleBtn не найден"
    body = m.group(1)
    assert 'class="trash-icon-closed"' in body
    assert 'class="trash-icon-open"' in body
    assert "#i-trash-closed" in body and "#i-trash-open" in body


def test_trash_drop_css():
    assert re.search(r"#trashToggleBtn\s*\{[^}]*overflow:\s*visible", CSS), \
        "#trashToggleBtn должен допускать выход бейджа (overflow: visible)"
    assert re.search(r"#trashToggleBtn\.drag-over\s*\{[^}]*scale\(", CSS), \
        "#trashToggleBtn.drag-over должен увеличивать иконку"
    assert re.search(r"#trashToggleBtn\.drag-over\s+\.trash-icon-open\s*\{[^}]*opacity:\s*1", CSS), \
        "Открытая крышка не показывается при dragover"
    assert re.search(r"#trashToggleBtn\s+\.badge\s*\{[^}]*inset-inline-end:\s*-5px", CSS), \
        "Бейдж корзины должен быть сдвинут в угол"


def test_image_and_project_set_trash_payload():
    assert "application/x-pdb-trash-item" in MAIN, \
        "dragstart не выставляет application/x-pdb-trash-item"
    assert re.search(
        r"JSON\.stringify\(\{\s*type:\s*'image',\s*ids\s*\}\)", MAIN
    ), "изображения не кладут type: image в trash-payload"
    assert re.search(
        r"type:\s*'project',\s*id:\s*p\.id", MAIN
    ), "проекты не кладут type: project в trash-payload"


def test_trash_drop_handler_wired():
    assert "function _wireTrashDropTarget" in MAIN
    assert re.search(r"addEventListener\('dragover'", MAIN), "нет dragover-обработчика"
    assert re.search(r"addEventListener\('drop'", MAIN), "нет drop-обработчика"
    assert "_wireTrashDropTarget()" in MAIN, "обработчики корзины не регистрируются"
