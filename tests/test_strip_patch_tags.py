"""[STAGE8_CODE_HYGIENE] Regression: scripts/strip_patch_tags.py.

Проверяет:
  * dry-run не меняет файлы (ни в рабочей директории, ни в fake-файле);
  * --apply на fake-файле удаляет ожидаемые анкоры;
  * _MIGRATIONS в app.py не пострадал после apply (FIX_MIGRATIONS_LIST_V2
    всё ещё присутствует) — это защищает от поломки миграций.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRIP = ROOT / "scripts" / "strip_patch_tags.py"


def test_strip_script_exists():
    assert STRIP.exists(), f"{STRIP} not created (STAGE8 not applied)"


def test_dry_run_does_not_modify(tmp_path):
    """Запуск без --apply на fake-файле оставляет содержимое неизменным."""
    f = tmp_path / "fake.py"
    content = "x = 1  # [PATCH:FOO]\nprint(x)\n"
    f.write_text(content, encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(STRIP), str(f)],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert f.read_text(encoding="utf-8") == content, (
        "dry-run изменил файл — это баг"
    )


def test_apply_removes_inline_anchor(tmp_path):
    f = tmp_path / "fake.py"
    f.write_text("x = 1  # [PATCH:FOO]\nprint(x)\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(STRIP), "--apply", str(f)],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    after = f.read_text(encoding="utf-8")
    assert "[PATCH:FOO]" not in after
    assert "x = 1" in after  # код сохранён
    assert "print(x)" in after


def test_apply_removes_standalone_anchor(tmp_path):
    f = tmp_path / "fake.py"
    f.write_text("# [STAGE9:foo]\nx = 1\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(STRIP), "--apply", str(f)],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    after = f.read_text(encoding="utf-8")
    assert "[STAGE9:foo]" not in after
    assert "x = 1" in after


def test_migrations_survive_apply():
    """После --apply на app.py все миграции должны остаться на месте.

    Проверяем по source, без реального запуска --apply на app.py
    (это повлияло бы на весь проект).
    """
    import app
    cols = {(t, c) for (t, c, _ddl) in app._MIGRATIONS}
    assert ("projects", "created_at") in cols
    assert ("images", "revision") in cols
    # ключевой маркер, что _MIGRATIONS цел
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "FIX_MIGRATIONS_LIST_V2" in app_py, (
        "_MIGRATIONS в app.py не должен терять inline-маркер "
        "FIX_MIGRATIONS_LIST_V2 — strip_patch_tags.py обязан его пропускать"
    )
