"""[STAGE0-3-js-test] Регрессия: `t.X` в submitProjectModal (t — i18n функция)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Поля, которые должны жить только на target./info./_projectModalTarget
# Никогда на глобальной функции t (i18n translation).
_TARGET_FIELDS = (
    "data_retention_days",
    "auto_blur_classes",
    "trash_ttl_days_override",
    "thumbnail_size",
    "default_zoom",
)


def test_no_t_target_confusion():
    """Ищем `t.<field>` где field — известное поле target-объекта.

    Регекс с lookbehind/lookahead исключает false-positive на
    `target.<field>` (t из target предшествуется 'e', а не '('/' ').
    """
    src = (ROOT / "js" / "main.js").read_text(encoding="utf-8")
    for field in _TARGET_FIELDS:
        pattern = re.compile(
            r'(?<![A-Za-z0-9_])t\.' + re.escape(field) + r'\b'
        )
        m = pattern.search(src)
        assert m is None, (
            f"Найден баг: t.{field} (позиция {m.start() if m else '?'}). "
            f"Должно быть target.{field} — t это i18n-функция, "
            f"t.{field} === undefined."
        )


def test_fix_actually_present():
    """После фикса target.X должен присутствовать в submitProjectModal."""
    src = (ROOT / "js" / "main.js").read_text(encoding="utf-8")
    assert "target.data_retention_days" in src, \
        "target.data_retention_days отсутствует — фикс не применён?"
    assert "target.auto_blur_classes" in src, \
        "target.auto_blur_classes отсутствует — фикс не применён?"
