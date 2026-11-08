# ADR-0008: Rate limiter multi-worker

## Статус
Accepted (Stage 5)

## Контекст
`SimpleRateLimiter` — in-memory. При `uvicorn --workers N` каждый воркер
держит свой счётчик, лимит фактически умножается на N. Для login-лимитов
это дыра (brute-force проходит в N раз больше попыток).

## Решение
`fail_mode="closed"` (default):
- login/brute-force лимиты (`max_requests ≤ 10`) — `RateLimitUnavailable` → 503;
- тяжёлые операции (`max_requests > 10`) — `fail_mode="open"` (degraded-open).

## Последствия
+ Brute-force не пройдёт «тихо».
+ Тяжёлые операции не блокируются.
− `WEB_CONCURRENCY>1` требует Redis-based limiter (roadmap).
