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
