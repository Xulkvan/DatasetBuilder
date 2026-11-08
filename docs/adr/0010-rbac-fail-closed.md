# ADR-0010: RBAC fail-closed

## Статус
Accepted (Stage 5)

## Контекст
`route_permissions._RULES` покрывал не все `/api/*`. Не зарегистрированные
роуты в team mode проходили любому аутентифицированному пользователю
(скрытая дыра). Найти её было сложно — не 403, а «работает».

## Решение
`match_permission` возвращает `"__deny__"` для `/api/*` без правила
(кроме whitelist). Middleware в `app.py` → 403 `Route not registered in RBAC`.

Whitelist: `/api/auth/`, `/api/setup/`, `/api/v2/`,
`/api/health`, `/api/metrics`, `/api/version`.

Правила для ранее не покрытых роутов добавлены (`_READ_ANNOTATION_WRITE`,
`_WRITE_SPECIFIC`).

## Последствия
+ Новый роут без RBAC-правила сразу 403 (а не «тихо работает»).
+ Единая политика.
− При добавлении роутов нужно помнить про `_RULES`. Покрыто
  `tests/test_stage5_rbac_complete.py` (статика + runtime).
