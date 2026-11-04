# ADR-0004: CSRF double-submit cookie

## Статус
Accepted (V14.4.5)

## Контекст
В team mode сессия хранится в HttpOnly cookie `pdb_session`. Cookie
автоматически отправляется браузером на каждый запрос — это классический
CSRF-вектор: сторонний сайт может инициировать POST/PUT/DELETE от имени
пользователя.

Заголовок `X-Requested-With: DatasetBuilder` (использовался ранее) —
слабая защита: простой JavaScript на стороннем сайте может его выставить.

## Решение
Double-submit cookie:

1. При логине сервер выставляет два cookie:
   * `pdb_session` — HttpOnly, `SameSite=Strict`;
   * `pdb_csrf` — **не** HttpOnly, `SameSite=Strict` (читается из JS).
2. Клиент (js/api.js) на каждый write-запрос читает `pdb_csrf` и отправляет
   его в заголовке `X-CSRF-Token`.
3. Сервер (security.py) сравнивает `X-CSRF-Token` с `pdb_csrf` через
   `secrets.compare_digest` — оба должны присутствовать и совпадать.

Дополнительно: `X-Requested-With` остаётся вторым слоем (простые формы
его не выставляют). `SameSite=Strict` — третий слой.

`CSRF_STRICT=0` отключает double-submit для тестов; `X-Requested-With`
проверяется всегда.

## Последствия
+ Stateless: не нужны серверные CSRF-токены per session.
+ Работает с cookie-аутентификацией.
+ `secrets.compare_digest` защищает от timing-атак.
+ Три независимых слоя (custom header + double-submit + SameSite).
− Cookie `pdb_csrf` видна JS → XSS может её прочитать. Компенсация:
  CSP + `HttpOnly` на сессии; CSRF-token не даёт доступа к сессии.
− Для API v2 (Bearer) CSRF не применяется — Bearer нельзя отправить
  автоматически из HTML-формы. `X-Requested-With` там тоже не нужен.

## Альтернативы
1. **Synchronizer token** (token в БД per session) — надёжнее, но
   требует state и инвалидации. Overkill для self-hosted.
2. **SameSite=Strict only** — не работает в старых браузерах (< 2016)
   и ломается при открытии из bookmark.
3. **Origin/Referer check** — менее надёжно, чем double-submit; Referer
   часто отключён.
4. **JWT в Authorization** — не подходит: хотим HttpOnly (защита от XSS).
