# ADR-0001: Local vs Team mode

## Статус
Accepted (V14.0.0)

## Контекст
DatasetBuilder — self-hosted инструмент для разметки датасетов. Основной
сценарий — соло-разработчик или небольшая команда. Требовалось:

* не нагружать соло-пользователя настройкой логина / ролей;
* обеспечить полноценную multi-user работу (роли, назначения, блокировки)
  для команды 5–20 человек с Postgres.

Один кодовый base — ключевое требование, чтобы не дублировать UI и API.

## Решение
Единый codebase, режим выбирается через env `AUTH_MODE` (`auto|local|team`)
и `DB_ENGINE` (`sqlite|postgres|mysql`):

* `AUTH_MODE=auto` (default): `local` для SQLite, `team` для Postgres/MySQL.
* `local`  — глобальный `SuperAdmin` (id=0), экран логина скрыт, все права.
* `team`   — cookie-сессии (`pdb_session`), роли Admin/Manager/Annotator/Reviewer,
              матрица прав в `config.ROLE_PERMISSIONS` + RBAC-middleware.

Фронт определяет режим через `/api/auth/status` и переключает UI.

## Последствия
+ Нет дублирования кода между «соло» и «командной» версиями.
+ Легко мигрировать: пользователь включает team mode, включает Postgres —
  БД мигрирует через встроенный MySQL→SQLite мигратор.
+ Один набор тестов покрывает оба режима (см. `tests/test_smoke_*`).
− Auth-related код всегда присутствует в памяти (несколько middleware,
  session-модель, RBAC). Плата — ~3–5 % cold-start и complexity.
− В local mode требуется guard от случайного включения team: защита
  через `_needs_setup()` и явную ошибку при DB_PASSWORD=root в проде.

## Альтернативы
1. Два отдельных приложения (local.py / team.py) — отклонено: 80 % кода общее.
2. Всегда team mode — отклонено: отпугивает соло-пользователей.
3. Feature-flag в UI без серверного переключения — отклонено: RBAC
   на сервере обязателен, UI-флаг легко подделать.
