"""Stage 3: command palette — no View Transitions, standard modal animation."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_open_command_palette_no_with_view_transition():
    src = (ROOT / "js" / "command_palette.js").read_text(encoding="utf-8")
    assert "withViewTransition" not in src, (
        "js/command_palette.js всё ещё использует withViewTransition — "
        "Stage 3 не применён (палитра будет мигать)"
    )


def test_open_modal_handles_command_palette():
    src = (ROOT / "js" / "ui.js").read_text(encoding="utf-8")
    assert "querySelector(':scope > .command-palette')" in src, (
        "openModal не расширен на .command-palette — "
        "modal-animating не будет ставиться на палитру"
    )
