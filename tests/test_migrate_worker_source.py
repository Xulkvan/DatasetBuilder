"""Regression: _migrate_worker живет только в services.migrate_service.

До QUALITY-F2-CLEANUP в app.py был dead-блок _migrate_worker, который
ссылался на MIGRATE_STATE/MIGRATE_LOCK/MIGRATE_THREAD - не определенные
в app.py (NameError при вызове). Блок дублировал services/migrate_service.py.
"""
import inspect


def test_app_does_not_export_dead_migrate_worker():
    import app as app_mod
    for name in (
        "_migrate_worker",
        "_MIGRATION_ORDER",
        "_count_rows",
        "_copy_table_orm",
        "_sqlite_target_path",
        "_env_file_path",
        "_snapshot_env",
        "_restore_env",
        "_update_env_file",
    ):
        assert not hasattr(app_mod, name), (
            f"app.{name} все еще существует - QUALITY-F2-CLEANUP не применен "
            f"(dead block в app.py)"
        )


def test_service_migrate_worker_is_callable():
    from services.migrate_service import _migrate_worker
    assert callable(_migrate_worker)


def test_app_module_has_no_migrate_state_refs():
    """app.py не должен ссылаться на MIGRATE_STATE/MIGRATE_LOCK/MIGRATE_THREAD."""
    import app as app_mod
    src = inspect.getsource(app_mod)
    for name in ("MIGRATE_STATE", "MIGRATE_LOCK", "MIGRATE_THREAD"):
        assert name not in src, (
            f"{name} встречается в app.py - либо dead code, либо импорт без alias. "
            f"Перенесите в services.migrate_service."
        )


def test_storage_router_still_imports_worker():
    """routers/storage.py должен импортировать сервисную версию."""
    import routers.storage as storage_mod
    src = inspect.getsource(storage_mod)
    assert "services.migrate_service" in src
    assert "_migrate_worker" in src
