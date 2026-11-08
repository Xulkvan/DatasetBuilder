# ADR-0007: SSRF protection for RTSP / HTTP streams

## Статус
Accepted (Stage 5)

## Контекст
`create_stream` принимал произвольный URL и передавал в `cv2.VideoCapture`.
`file:///etc/passwd` мог обойти проверку, `http://169.254.169.254` —
утечь в metadata. `start_stream_worker` повторно открывал URL без проверки.

## Решение
Единая валидация `services.url_safety.validate_stream_url`:
- схема только `rtsp`, `rtsps`, `rtmp`, `http`, `https`;
- для `http/https` — `is_safe_external_url` (private/loopback/metadata);
- вызов и в `create_stream`, и в `start_stream_worker` (defense-in-depth).

## Последствия
+ `file://`, `http://127.*`, `http://169.254.169.254` → 400.
+ Единая точка правды.
− Публичные внутренние камеры (LAN) нужно явно разрешать вне этой проверки
  (см. будущий ADR, если понадобится).
