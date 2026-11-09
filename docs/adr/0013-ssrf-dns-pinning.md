# ADR-0013: SSRF DNS pinning

## Статус
Accepted (V15.7.0)

## Контекст
`services/url_safety.is_safe_external_url` использует double-resolve
(getaddrinfo дважды с паузой 50 мс). Это ловит наивный DNS rebinding,
но не защищает от «умного» атакующего, который держит первый resolve
публичным до 50 мс, а затем меняет DNS на приватный. К моменту
фактического connect (urllib/httpx) IP уже приватный — TOCTOU.

Для критичных B2B-сценариев (webhooks, внешние импорты, import URL)
требуется defense-in-depth: жёстко привязать сокет к проверенному
IP и передать исходный hostname только через заголовок `Host`.

## Решение
Новый модуль `services/safe_http_client.py`:

* `_PinnedTransport(httpx.HTTPTransport)` — для каждого `http://`-запроса:
  1. `socket.getaddrinfo(host, port)` — resolve один раз;
  2. каждый IP проверяется через `_is_private_ip` (loopback / private /
     link-local / reserved / multicast / `0.0.0.0/8`); при первом
     приватном — `httpx.ConnectError`;
  3. выбирается первый публичный IP (`_pin_ip`);
  4. URL пересобирается с `host=_pin_ip`, оригинальный hostname
     уходит в заголовок `Host`;
  5. `super().handle_request(new_req)` — connect идёт на `_pin_ip`,
     никакого повторного DNS-resolve.

* Для `https://`-запросов `_PinnedTransport` откатывается на
  `is_safe_external_url` (double-resolve) — TLS SNI-ограничение
  (см. ниже).

* `get_safe_client(timeout)` — фабрика `httpx.Client` с этим транспортом.

Используется в:
* `services/external_import_service._download_to_file`,
  `_http_get_json`, `_http_post_json` — все внешние fetch;
* `services/webhook_service._post_once` — при `WEBHOOK_ALLOW_PRIVATE=0`.

## Ограничения
* **HTTPS + TLS SNI.** `httpx.HTTPTransport` не передаёт отдельный SNI
  при подключении к bare IP. При `https://<pin_ip>` TLS-handshake идёт
  с `SNI=<pin_ip>`, что ломает vhost-based серверы (CDN, облачные API).
  Поэтому для `https://` pinning не применяется — используется
  double-resolve (`is_safe_external_url`). Это документированный
  компромисс: HTTPS остаётся уязвим к «умному» rebinding, но
  double-resolve ловит наивные атаки.

* **`WEBHOOK_ALLOW_PRIVATE=1`** — pinning отключается полностью
  (`get_safe_client` не вызывается; используется обычный
  `httpx.Client`). Это dev-режим, для production не рекомендуется
  (см. ADR-0005, ADR-0007).

## Последствия
+ HTTP-запросы защищены от DNS rebinding на уровне connection
  (TOCTOU закрыт — connect идёт на pin_ip).
+ Единая точка правды для внешних fetch — `safe_http_client`.
+ Повторные вызовы к одному хосту делают resolve на каждый запрос,
  но pin_ip стабилен в рамках одного запроса.
− HTTPS использует fallback (double-resolve) — ограничение
  документировано выше.
− `httpcore`-level network backend (архитектурно правильный)
  отложен до появления реальной потребности.

## Альтернативы
1. **httpcore.ConnectionPool + custom network_backend** — правильно,
   но требует ~100 LOC, тонкой настройки TLS (SNI) и тестирования.
   Отложено до реальной потребности.
2. **Только fail-closed по IP** (никогда не разрешать хосты, у
   которых хоть один IP приватный) — уже сделано в
   `is_safe_external_url` (Stage 4), но без pinning.
3. **Заменить httpx на aiohttp/requests** — не решает TOCTOU (тот же
   паттерн: resolve → connect).
