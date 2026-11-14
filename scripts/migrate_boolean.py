"""[STAGE14] One-shot DB migration: users.must_change_password Integer → Boolean.

Запуск вручную:
    ALLOW_DB_MIGRATION=1 python -m scripts.migrate_boolean

Или автоматически при старте приложения, если установлен
ALLOW_DB_MIGRATION=1 (см. _migrate_must_change_password_boolean_guarded
в app.py, зарегистрирован в _POST_CREATE_MIGRATIONS).

ВАЖНО: lossy для SQLite — пересоздаёт таблицу users. FK-зависимости
(sessions, image_locks, user_project_access) сохраняются, т.к. ids
не меняются. PostgreSQL — ALTER COLUMN TYPE BOOLEAN. MySQL —
MODIFY TINYINT(1) (SQLAlchemy трактует как Boolean).

Автоматический запуск при старте без ALLOW_DB_MIGRATION=1 запрещён
(см. AGENTS.md → «Данные, Контракты, Codegen И Миграции»).
"""
from __future__ import annotations

import logging
import os
import sys

from sqlalchemy import inspect, text

from database import DB_ENGINE, engine

log = logging.getLogger("db")


def _users_has_boolean_column() -> bool:
    """True если must_change_password уже Boolean (или таблица/колонка отсутствует)."""
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return True
    for col in insp.get_columns("users"):
        if col["name"] == "must_change_password":
            type_name = str(col["type"]).upper()
            if "BOOL" in type_name:
                return True
            if DB_ENGINE == "mysql" and "TINYINT" in type_name:
                return True  # Boolean == TINYINT(1) в MySQL
            return False
    return True


def _migrate_must_change_password_boolean() -> bool:
    """Integer → Boolean.

    Возвращает True если миграция выполнена, False если не требуется.
    """
    if _users_has_boolean_column():
        log.info(
            "migrate_boolean: users.must_change_password already BOOLEAN "
            "(or no migration needed)"
        )
        return False

    if DB_ENGINE == "sqlite":
        # PRAGMA foreign_keys должен быть установлен вне транзакции —
        # используем raw_connection.
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute("PRAGMA foreign_keys=OFF")
            cur.execute(
                """
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(64) NOT NULL UNIQUE,
                    password_hash VARCHAR(256) NOT NULL DEFAULT '',
                    role VARCHAR(32) NOT NULL DEFAULT 'annotator',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NULL,
                    must_change_password BOOLEAN NOT NULL DEFAULT 0,
                    full_name VARCHAR(128) NULL,
                    temp_password VARCHAR(128) NULL
                )
                """
            )
            cur.execute(
                """
                INSERT INTO users_new
                    (id, username, password_hash, role, is_active,
                     created_at, must_change_password, full_name, temp_password)
                SELECT id, username, password_hash, role, is_active,
                       created_at,
                       CASE WHEN must_change_password = 0 THEN 0 ELSE 1 END,
                       full_name, temp_password
                FROM users
                """
            )
            cur.execute("DROP TABLE users")
            cur.execute("ALTER TABLE users_new RENAME TO users")
            raw.commit()
            cur.execute("PRAGMA foreign_keys=ON")
            raw.commit()
        finally:
            raw.close()
        log.warning(
            "migrate_boolean: SQLite users table recreated with BOOLEAN"
        )
        return True

    if DB_ENGINE == "postgres":
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE users ALTER COLUMN must_change_password "
                    "TYPE BOOLEAN USING "
                    "(CASE WHEN must_change_password = 0 THEN FALSE ELSE TRUE END)"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE users ALTER COLUMN must_change_password "
                    "SET DEFAULT FALSE"
                )
            )
        log.info(
            "migrate_boolean: PostgreSQL users.must_change_password → BOOLEAN"
        )
        return True

    # MySQL
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE users MODIFY must_change_password "
                "TINYINT(1) NOT NULL DEFAULT 0"
            )
        )
    log.info(
        "migrate_boolean: MySQL users.must_change_password → TINYINT(1)"
    )
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if os.getenv("ALLOW_DB_MIGRATION") != "1":
        print(
            "ERROR: Set ALLOW_DB_MIGRATION=1 to run this migration",
            file=sys.stderr,
        )
        sys.exit(1)
    _migrate_must_change_password_boolean()
