"""STAGE15 — Responsive Breakpoints & Dynamic Type (em-based).

Регрессия: px в @media (max-width) ломает Dynamic Type (Safari → View →
Zoom Text Only). Safari увеличивает базовый font-size, и px-медиазапросы
не учитывают масштабирование → сетка ломается на разных уровнях зума.

Fix: все @media (max-width: Npx) заменены на @media (max-width: Nem)
(N / 16 — базовая 16px).

STAGE15.
"""
import re
from pathlib import Path


def test_no_px_in_media_queries():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    matches = re.findall(r"@media[^{]+\(m(?:ax|in)-width:\s*\d+px\)", css)
    assert not matches, f"Медиа-запросы в px найдены: {matches}"


def test_em_media_queries_present():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    for em in ("68.75em", "55em", "45em"):
        assert f"max-width: {em}" in css, (
            f"Ожидался @media (max-width: {em}) — не найден"
        )


def test_main_and_modal_use_sp_tokens():
    css = (Path(__file__).parent.parent / "style.css").read_text(encoding="utf-8")
    m = re.search(r"\.main\s*\{[^}]*\}", css)
    assert m, ".main rule not found"
    assert "var(--sp-" in m.group(0), ".main padding should use var(--sp-*)"
    assert "--modal-pad: var(--sp-" in css, "--modal-pad должен использовать var(--sp-*)"
