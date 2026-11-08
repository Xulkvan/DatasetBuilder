# ADR-0011: Full project backup format

## Статус
Accepted (V14.11.0)

## Контекст
Нужен способ перенести проект на другое устройство без потери данных.
Существующий `backup_project` создаёт zip, но без обратного импорта.
COCO/YOLO теряют behavior/animal_id/keypoints/versions/blur.

## Решение
Один self-contained zip. Контракт — `schemas_backup.py`.

**Переносится:** Project, ProjectKeypointSchema, Video, Image,
Annotation, Keypoint, Tag, ImageTag, DatasetVersion, BlurRegion,
BehaviorValidation.

**Опционально (флаги, по умолчанию выключены):**
- Stream: URL может содержать credentials; при импорте `is_active=False`,
  worker не стартует.
- Webhook: `secret_key` **не переносится**; при импорте `None`.

**Не переносится:** User, Session, ImageLock, AuditLog,
UserProjectAccess — сессионные / security-sensitive.

## Security
- `webhooks.json` с `secret_key` → импорт отклоняется 400 (не warning).
- `Stream.url` с `user:pass@` → импорт отклоняется 400.
- `img.filename` из архива проходит `validate_user_filename` +
  `sanitize_display_name`.
- `_safe_extract_zip` (zip-slip, zip-bomb), `MAX_IMPORT_BYTES`.

## Версионирование
`format_version` — целое. Добавление опциональных полей → минорное;
удаление/переименование → мажорное.

## Последствия
+ Перенос данных без потерь (behavior, animal_id, keypoints, versions,
  blur, валидации).
+ Работает между ОС: пути относительные, файлы копируются байт-в-байт.
+ Транзакционно: при сбое БД не остаётся в полу-состоянии.
+ `calculate_dataset_hash` после импорта совпадает с оригиналом.
− Размер архива ≈ размер `uploads/` + `videos/`.
− `assigned_to`/`reviewed_by` маппятся по username; если пользователя
  нет — `null` + warning.
− `Stream` / `Webhook` требуют ручной донастройки после импорта.
