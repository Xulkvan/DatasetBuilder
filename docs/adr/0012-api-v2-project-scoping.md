# ADR-0012: API v2 project scoping

## Статус
Accepted (V15.6.0)

## Контекст
До V15.6.0 `/api/v2/*` использовал единственный `API_KEY` с глобальным
доступом ко всем проектам. Любой B2B-клиент с валидным токеном мог
читать и изменять датасеты **всех** проектов инстанса — классический
IDOR (Insecure Direct Object Reference).

Для B2B-сценария требовалось ограничить токен одним или несколькими
проектами без слома существующих клиентов.

## Решение
`API_KEY` может быть:

* **plain string** (`secret123`) — глобальный доступ (backward compat);
* **JSON map** (`{"tokenA": {"projects": [1,2]},
  "tokenB": {"projects": "*"}}`) — scoped-доступ. Ключ — токен,
  значение — объект со списком `projects` (`*` = все).

Логика сосредоточена в `services/api_key.py`:

* `_load_api_key_config()` — парсит env (при неудачном JSON для строки,
  начинающейся с `{`, — fallback на plain + `log.warning`);
* `validate_api_key()` — проверяет Bearer (constant-time);
* `get_api_key_scope()` — возвращает scope токена (`None` для plain);
* `require_project_scope(request, project_id)` — 403, если проект не
  входит в scope;
* `get_allowed_projects_scope(request)` — для фильтрации списка проектов
  в `v2_list_projects`.

Все project-scoped эндпоинты `/api/v2/*` вызывают
`require_project_scope(request, project_id)` до основной логики.

## Последствия
+ Закрыт IDOR: один токен не даёт доступ ко всем проектам.
+ Plain string продолжает работать — backward compat.
+ Тест `tests/test_api_v2_scope.py` покрывает 6+ кейсов.
− Plain string, начинающаяся с `{`, трактуется как невалидный JSON →
  fallback на plain с warning. Документировано в README и `.env.example`.
− Scoped-конфиг без ключа `"projects"` → fail-closed (403).
  Покрыто тестом.

## Альтернативы
1. **Всегда fail-closed** (требовать JSON map) — отклонено: ломает
   существующих клиентов.
2. **Отдельная таблица `api_keys` в БД** — overkill для текущего
   масштаба; env-переменной достаточно.
3. **JWT-токены** — лишняя сложность; plain/JSON map проще и достаточно.
