# ADR-0014: Object-level авторизация для legacy-эндпоинтов

## Статус
Accepted (Stage 1)

## Контекст
RBAC-middleware (`services/route_permissions.py`) проверяет только
route-level permission. Legacy-эндпоинты `app.py` и часть роутеров не
вызывали `check_project_access` / `check_image_access`, поэтому в team
mode любой пользователь с нужной ролью мог читать и изменять чужие
проекты, изображения, видео и вебхуки (IDOR).

Номер `0007` уже занят (`0007-ssrf-stream-protection.md`), поэтому
решение зафиксировано как ADR-0014.

## Решение
Route-level RBAC дополняется object-level проверкой доступа к сущности:

- `check_project_access(db, project_id, user)` — проект.
- `check_image_access(db, image_id, user)` — изображение и его проект;
  annotator не получает доступ к чужим назначенным изображениям.
- `ensure_video_access(db, video_id, user)` — видео и его проект;
  удалённое видео → 404.

Проверки добавлены в legacy-эндпоинты `app.py` (видео, экспорт, валидация,
дубликаты, similar/copy/predict/autolabel_debug, bulk_rename, track
status/stop/events/metrics, agtech CSV) и в `routers/backup.py`,
`routers/webhooks.py`, `routers/locks.py`, `routers/autolabel_batch.py`,
`routers/ml.py`, `routers/train.py`, `routers/images.py`.

Для track-эндпоинтов дополнительно сверяется `TRACK_STATE.video_id`:
чужой/завершённый трекинг не отдаёт свой прогресс.

`save_annotations` отклоняет `AnnotationIn.id`, которого нет на этом
изображении, — нельзя «утащить» аннотацию из чужого кадра.

## Последствия
+ Объектная проверка выполняется на границе роутера, до бизнес-логики.
+ Один класс ошибок: 403 `error.forbidden` / 404 `error.*NotFound`.
+ Покрыто `tests/test_idor*.py`.

− Каждый новый эндпоинт с `project_id` / `image_id` / `video_id` обязан
  вызывать соответствующую проверку. CI-grep по `app.py` ловит пропуски
  для `@app.*` (кроме health/static/`/api/v2`).
