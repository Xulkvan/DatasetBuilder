"""[Patcher 9] Regression: setup_wizard uses native <dialog>, not div.modal-backdrop.

Bug F-03: до патчера openSetupWizard создавал `<div class="modal-backdrop">`
динамически (с z-index: 99999), игнорируя нативную семантику <dialog> и
фокус-трап браузера.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SW = ROOT / "js" / "setup_wizard.js"
HTML = ROOT / "index.html"


def test_setup_wizard_uses_open_modal():
    src = SW.read_text(encoding="utf-8")
    assert "createElement('div')" not in src, (
        "js/setup_wizard.js всё ещё создаёт <div> — F-03 не применён"
    )
    assert "modal-backdrop" not in src, (
        "js/setup_wizard.js использует класс modal-backdrop"
    )
    assert "window.openModal('setupWizardModal')" in src, (
        "js/setup_wizard.js не вызывает window.openModal('setupWizardModal')"
    )


def test_setup_wizard_dialog_exists_in_html():
    html = HTML.read_text(encoding="utf-8")
    assert '<dialog id="setupWizardModal"' in html, (
        "#setupWizardModal должен быть <dialog> (STAGE 11 migration)"
    )
