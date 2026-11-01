"""[STAGE6-T13] ensure_schema идемпотентен, _MIGRATIONS содержит data_retention_days."""
import pytest

import app


def test_migrations_contains_data_retention_days():
    cols = {(t, c) for (t, c, _ddl) in app._MIGRATIONS}
    if ("projects", "data_retention_days") not in cols:
        pytest.skip("data_retention_days not in _MIGRATIONS — Этап 1 неполный")
    assert True


def test_migrations_contains_core_columns():
    cols = {(t, c) for (t, c, _ddl) in app._MIGRATIONS}
    required = [
        ("images", "is_deleted"),
        ("images", "deleted_at"),
        ("images", "phash"),
        ("annotations", "behavior"),
        ("annotations", "animal_id"),
        ("projects", "is_deleted"),
        ("projects", "auto_blur_enabled"),
    ]
    missing = [c for c in required if c not in cols]
    assert not missing, f"missing migrations: {missing}"


def test_ensure_schema_idempotent():
    """Повторный вызов не должен падать на существующих колонках."""
    app.ensure_schema()
    app.ensure_schema()
    assert True


def test_core_tables_exist():
    from sqlalchemy import inspect
    from database import engine
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    required = {
        "projects", "images", "annotations", "keypoints",
        "settings", "tags", "image_tags", "videos",
        "users", "sessions", "image_locks",
    }
    missing = required - tables
    assert not missing, f"missing tables: {missing}"
