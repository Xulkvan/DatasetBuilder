# ADR-0009: Model supply-chain (SHA256)

## Статус
Accepted (Stage 5)

## Контекст
`bootstrap_service` скачивает YOLO-модели с GitHub releases без проверки
целостности. Скомпрометированный CDN/MITM мог подложить свою модель.

## Решение
`config.YOLO_MODEL_SHA256: dict[str, str]` — известные хеши. После скачивания
`_verify_model_sha256(path, fname)`. При несовпадении — файл удаляется,
`IOError`. Пустой dict → warning, но не блок (для локальной разработки).

## Последствия
+ MITM/CDN-компромисс обнаруживается.
+ Best-effort: без заполненного хеша защиты нет.
− `YOLO_MODEL_SHA256` нужно поддерживать при обновлении моделей.
