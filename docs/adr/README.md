# Architecture Decision Records

Архитектурные решения проекта DatasetBuilder. Формат — [Michael Nygard ADR](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

| ID | Решение | Статус |
|----|---------|--------|
| [0001](0001-local-vs-team-mode.md) | Local vs Team режим | Accepted |
| [0002](0002-image-letterbox-640.md) | Letterbox 640×640 | Accepted |
| [0003](0003-sqlite-vs-postgres.md) | SQLite vs PostgreSQL | Accepted |
| [0004](0004-csrf-double-submit.md) | CSRF double-submit cookie | Accepted |
| [0005](0005-ssrf-protection.md) | SSRF protection | Accepted |
| [0006](0006-api-v2-fail-closed.md) | API v2 fail-closed | Accepted |
| [0007](0007-ssrf-stream-protection.md) | SSRF для RTSP/HTTP стримов | Accepted |
| [0008](0008-rate-limiter-multiworker.md) | Rate limiter multi-worker | Accepted |
| [0009](0009-model-supply-chain.md) | Model SHA256 supply-chain | Accepted |
| [0010](0010-rbac-fail-closed.md) | RBAC fail-closed | Accepted |
| [0011](0011-full-backup-format.md) | Full project backup format | Accepted |
| [0012](0012-api-v2-project-scoping.md) | API v2 project scoping | Accepted |
| [0013](0013-ssrf-dns-pinning.md) | SSRF DNS pinning | Accepted |

## Шаблон нового ADR

```markdown
# ADR-NNNN: <Решение>

## Статус
Proposed

## Контекст
<Почему возник вопрос>

## Решение
<Что решили>

## Последствия
<Плюсы, минусы, риски>

## Альтернативы
<Что рассматривали>
```
