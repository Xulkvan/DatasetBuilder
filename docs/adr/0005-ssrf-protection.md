# ADR-0005: SSRF protection

## Статус
Accepted (V14.4.3)

## Контекст
Функции, где пользователь задаёт URL, который сервер затем сам скачивает:

* `import/url` (импорт zip/картинки по ссылке);
* `import/roboflow`, `import/supervisely`, `import/labelbox`,
  `import/scale`, `import/darwin` — внешние API + download_url;
* Webhooks (`annotation.saved`, `training.completed`, `dataset.exported`).

Без проверки злоумышленник может заставить сервер обратиться к:

* `http://127.0.0.1:8000/api/...` — внутренние эндпоинты;
* `http://169.254.169.254/latest/meta-data/` — AWS metadata (утечка IAM-токенов);
* `http://192.168.x.x/` — внутренние сервисы.

## Решение
Единая проверка `services.url_safety.is_safe_external_url(url)`:

1. Схема только `http` / `https`.
2. DNS resolve через `socket.getaddrinfo`.
3. Каждый IP проверяется через `ipaddress.ip_address`:
   * `is_private`, `is_loopback`, `is_link_local`, `is_reserved`,
     `is_multicast`, `0.0.0.0/8` — блок.
4. **Double-resolve** с задержкой 50 мс — защита от DNS rebinding
   (TOCTOU: первый resolve публичный, второй — приватный). Если IP-наборы
   различаются — блок.

Webhooks дополнительно управляются `WEBHOOK_ALLOW_PRIVATE=1` (для
локальной разработки; в проде — 0).

## Последствия
+ Единая точка блокировки для всех внешних fetch.
+ Double-resolve ловит простейший rebinding.
+ Прозрачное логирование: `webhook blocked (private IP): <url>`.
− Полноценный DNS pinning не реализован: HTTPS + SNI несовместимы
  с подменой URL на IP без хаков. Прагматично: для self-hosted достаточно.
− Double-resolve добавляет 50 мс к каждому внешнему fetch. Приемлемо
  для фоновых операций; для hot-path — нет.
+ IPv6-mapped IPv4 (`::ffff:127.0.0.1`) блокируется: `_is_private_ip` разворачивает адрес через `ipv4_mapped` и проверяет как IPv4.

## Альтернативы
1. **URL allowlist** — жёстко, но не работает для пользовательских
   импортов и произвольных webhook-endpoint.
2. **DNS pinning с кастомным TLS-контекстом** — правильно, но требует
   переписывания `urllib` / `httpx` и SNI-хаков.
3. **Файрвол egress** — не наш слой; должен быть на уровне deployment.
4. **Отключить все импорты** — потеря 80 % feature value.
