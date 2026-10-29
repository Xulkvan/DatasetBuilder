<div align="center">

# 🤖 DatasetBuilder

**Инструмент для разметки датасетов с авторазметкой на YOLOv8 / YOLO11**

От загрузки фото до обученной модели и готового B2B API — всё в одном веб-интерфейсе.

[![Version](https://img.shields.io/badge/version-14.1.0-0071e3?style=flat-square)](https://github.com/Xulkvan/DatasetBuilder)
[![Python](https://img.shields.io/badge/python-3.13%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLite | MySQL](https://img.shields.io/badge/DB-SQLite%20%7C%20MySQL-4479A1?style=flat-square)]()
[![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-FF6B35?style=flat-square)](https://github.com/ultralytics/ultralytics)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue?style=flat-square)](LICENSE)

</div>

---

## ✨ Что это

**DatasetBuilder** — веб-приложение и B2B-платформа для быстрой разметки датасетов с полным циклом:

0. **🚀 Full Pipeline** — нажатие одной кнопки прогоняет весь проект по 4 этапам (рамки → скелеты → треки → поведение) и выдает готовый датасет.
1. **Загрузка** фото, RTSP-потоков, видео или импорт готового датасета (COCO / YOLO / CVAT / Label Studio / Roboflow / Supervisely / Labelbox / Scale AI / V7 Darwin).
2. **Авторазметка** — YOLOv8 рисует рамки сам, ты правишь.
3. **Скелет (17 точек)** — разметка позы животного, обучение pose-модели YOLOv8, авто-скелет одним кликом, **кастомные схемы скелета**.
4. **Поведение** — эвристика по геометрии или **ML-классификатор** (RandomForest), обученный на ваших данных.
5. **Трекинг** — ByteTrack присваивает животным постоянные номера, вектор движения на холсте.
6. **SAM-сегментация** — точная маска по клику на объекте.
7. **MLOps** — экспорт в **ONNX**, **Data Versioning (Diff)**, **Active Learning**, **Auto-Blur** приватных зон.
8. **Обучение** — детектор и pose-модель прямо из UI, live-графики метрик.
9. **Экспорт** — YOLO / COCO / YOLO-pose / COCO-keypoints, а также **Parquet**, **SQL**, **CVAT XML** и CSV атрибутов.

Всё работает **локально**: данные остаются на твоём компьютере, никаких облаков. Для B2B-интеграций доступен **Async SDK** и **API v2**.

---

## 🎬 Возможности

### 🚀 Full Pipeline (Автоматизация)
- **Кнопка «Полная разметка»** — запускает весь процесс разметки проекта за один клик.
- **4 этапа поочередно**: Авторазметка (YOLO) → Авто-скелеты (Pose) → Трекинг (ByteTrack) → Автоповедение.
- **Режимы работы**: «Добавлять» (сохраняет старое) и «Заменять» (с нуля).
- **Серверный воркер** — можно закрыть вкладку, процесс продолжится на сервере.
- **Живой прогресс** — текущий этап, полоса выполнения и лог в реальном времени. По завершении появляется одна кнопка «Готово».

### 📡 RTSP-стримы (Симуляция реального времени)
- Поддержка IP-камер (RTSP) с захватом кадров и авторазметкой на лету.
- **1 FPS** (настраивается) — OpenCV + активная YOLO-модель.
- **Авто-восстановление** — стримы перезапускаются после падения или перезагрузки сервера.
- Простейший IoU-трекер на лету для стримов (выдача `animal_id`).
- Управление через модалку «RTSP-стримы» (добавить, остановить, статус).

### 🔌 API v2 и Python SDK (B2B)
- **REST API** с Bearer-авторизацией (`API_KEY`).
- **Swagger документация**: `/api/docs` и `/api/redoc` с тегами.
- **Фоновые задачи**: async autolabel с поллингом статуса.
- **Python SDK**: `pip install ./sdk` — асинхронный клиент (`AsyncDatasetBuilderClient`) на базе `httpx` с методами `upload_batch`, `get_dataset_coco`, `start_training`.

### 🖼 Разметка рамок
- **Авторазметка** через YOLOv8 (OpenImages V7 / COCO / свои модели).
- **TTA (test-time augmentation)**, **Debug-режим** (⇧G), **SAM-сегментация** (M).
- **Мультивыбор**, **заморозка** (L), **Undo/Redo** (⌘Z / ⌘Y).
- **Zoom/Pan** — колесо, Ctrl+колесо, pinch, пробел+drag.

### 🦴 Скелет (Pose) и Кастомные схемы
- **17 точек скелета** по умолчанию.
- **Кастомные схемы**: в настройках проекта можно задать свои точки и их иерархию (table-editor).
- **Режим скелета** (⇧K) — клик ставит точку, правый клик отменяет, двойной — видимость.
- **Обучение pose-модели YOLOv8** прямо из UI.
- **Авто-скелет** — pose-модель размечает все рамки фото.
- **Экспорт** учитывает кастомные схемы (YOLO-pose, COCO-keypoints).

### 🧠 Поведение животного
- **6 классов**: eat, drink, lie, stand, walk, active.
- **Эвристика (bbox-relative)** — пороги привязаны к рамке, а не к кадру. Есть Grid Search калибровка.
- **ML-классификатор**: обучение RandomForest на ваших скелетах (в настройках проекта). Если классификатор уверен (>60%), он перебивает эвристику. Файлы хранятся per-project.
- **Ручная установка** — кнопки в панели или горячие клавиши 1..6.

### 🎯 Трекинг и ReID
- **ByteTrack** — автоматическое присвоение `animal_id` по видео.
- **ReID (восстановление ID)** — если свинья перекрыта, ID восстанавливается по эмбеддингу.
- **Панель треков** — слияние, переназначение, удаление, метрики разрывов.
- **Вектор движения** — визуализация перемещения bbox между кадрами.
- **Экспорт треков** в JSON и CSV.

### 🧪 MLOps и Data Versioning
- **Экспорт в ONNX** (кнопка у модели): `opset=12`, `simplify`, `dynamic`. Сохраняется в `models/`.
- **Версии датасета**: снимки (hash) в модалке `📋 Версии`.
- **Diff версий**: выбор двух версий чекбоксами и наглядное сравнение (добавлено/удалено фото и рамок).
- **Active Learning**: фильтр «Неуверенные» в сайдбаре — запрашивает у YOLO очередь кадров, где уверенность модели в диапазоне `[0.3, 0.6]`.

### 🔒 Безопасность и приватность
- **Auto-Blur**: автоматическое размытие фона (люди, машины, номера) на новых фото в фоне. Настраивается per-project.
- **CSRF** — заголовок `X-Requested-With`, **CSP**, защита от Zip-slip и path traversal.
- **Rate limiting** на тяжелые операции.

### 🎥 Видео
- **Извлечение кадров** через ffmpeg (mp4 / mov / avi / mkv / webm).
- **Кастомный плеер**: перемотка по кадрам, скорость, Seek-бар.
- **Точная отрисовка рамок**: исправлен баг с letterbox (рамки больше не растягиваются).
- **Переключатель** «Показывать рамки» в плеере.
- **Интерполяция bbox** между кадрами для плавности.

### 🤖 Обучение
- **Два режима**: детектор (bbox) и **pose** (скелет).
- **Fine-tune YOLOv8** (nano / small / medium) из UI.
- **Live-прогресс** через SSE + графики mAP/loss.
- **Сравнение моделей** side-by-side.
- **Автоактивация** новой модели и сохранение `last.pt` при остановке.

### 🎨 Организация и Интерфейс
- **Мультиклассовые проекты**, **Теги**, **Корзина** (с TTL).
- **Виртуальный скролл** (100k+ фото без тормозов), **Drag-n-drop** между проектами.
- **Apple HIG-inspired** дизайн — Liquid Glass, spring-анимации, haptics.
- **Тёмная / светлая / авто** тема, **Русский / English** интерфейс.
- **Command palette** (⌘K), **Focus-режим** (⌘\), **Горячие клавиши**.

---

## 🚀 Быстрый старт

### Требования
- **Python 3.13+**
- **MySQL 8.0+** *(опционально — по умолчанию SQLite)*
- **FFmpeg** *(опционально — для видео)*
- **scikit-learn** *(опционально — для ML-классификатора поведения)*
- **Docker + docker-compose** *(опционально — для деплоя без Python на хосте)*
- ОС: Windows 10+ / macOS 11+ / Linux

### Вариант 1: SQLite (рекомендуется)
```bash
git clone https://github.com/Xulkvan/DatasetBuilder.git
cd DatasetBuilder

python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

pip install -r requirements.txt
python run.py
```
Открой **http://localhost:8000** — БД создастся сама.

С авто-перезагрузкой при правке `.py`:
```bash
DEBUG=1 python run.py
```

### Вариант 2: MySQL
```sql
CREATE DATABASE pig_dataset CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```
Создай `.env` в корне проекта:
```env
DB_ENGINE=mysql
DB_USER=root
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=3306
DB_NAME=pig_dataset
```

### Вариант 3: Desktop (.exe / .app / .AppImage)

```bash
pip install pyinstaller
pyinstaller build.spec
# → dist/DatasetBuilder/
```

### Вариант 4: Docker (production-like)

```bash
git clone https://github.com/Xulkvan/DatasetBuilder.git
cd DatasetBuilder

# Создай .env (можно скопировать .env.example)
cp .env.example .env
# Опционально: впиши API_KEY, настрой лимиты

docker-compose up -d --build
```

Открой **http://localhost:8000**.

Данные (`data/`, `uploads/`, `models/`, `exports/`, `runs/` и т.д.) монтируются как bind-mount из хоста — контейнер можно пересоздавать без потери данных.

```bash
# Логи
docker-compose logs -f backend

# Остановка
docker-compose down

# Остановка + удаление контейнера (данные сохраняются)
docker-compose down --rmi local
```

**Что внутри контейнера:**
- Python 3.11-slim, `requirements.lock` для воспроизводимости
- FFmpeg, OpenCV headless, libgl1, libgomp1 — всё готово для YOLO
- Healthcheck на `/api/version` (curl каждые 30 с)
- По умолчанию SQLite (`DB_ENGINE=sqlite`)

### Установка Python SDK (для B2B)
```bash
pip install ./sdk
```

---

## ⚙️ Настройка

Все параметры через `.env` (см. `.env.example` как шаблон):

```env
# БД
DB_ENGINE=sqlite | mysql
DB_PATH=data/dataset.db                                # SQLite
DB_USER / DB_PASSWORD / DB_HOST / DB_PORT / DB_NAME    # MySQL

# Данные
DATA_ROOT=/custom/path

# Сервер
HOST=127.0.0.1
PORT=8000
DEBUG=0

# API v2 (Bearer auth)
API_KEY=your_secret_token_here

# Лимиты
MAX_UPLOAD_MB=50
MAX_IMPORT_MB=2048
MAX_VIDEO_MB=2048
MAX_VIDEO_FRAMES=3000
MAX_EXTRACTED_MB=10240

# Docker (опционально)
# DB_PATH=/app/data/dataset.db
# DATA_ROOT=/app
```

---

## 🗂 Структура проекта

```text
DatasetBuilder/
├── app.py              # FastAPI backend (сборка роутеров и middleware)
├── run.py              # точка входа (dev)
├── launcher.py         # desktop-обёртка (pywebview)
├── cli.py              # Headless CLI (run-pipeline)
├── security.py         # CSRF + CSP middleware
├── config.py           # Единый источник констант
├── database.py         # Настройка SQLAlchemy
├── models.py           # ORM-модели (Project, ImageModel, Stream, DatasetVersion и др.)
├── schemas.py          # Pydantic-схемы
├── logger.py           # Кастомный логгер статусов
├── version.py          # Версия и тип лицензии
├── build.spec          # PyInstaller spec
├── index.html          # UI
├── style.css           # стили
├── i18n.js             # словари ru/en
├── requirements.txt
├── requirements.lock   # зафиксированные версии для Docker
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── LICENSE
├── README.md
│
├── routers/            # Эндпоинты API
│   ├── api_v2.py       # B2B API с Bearer авторизацией
│   ├── images.py       # CRUD, загрузка, разметка
│   ├── ml.py           # авторазметка, SAM, поведение
│   ├── projects.py     # проекты, корзина, настройки, версии, стримы
│   ├── system.py       # логи, версии
│   ├── pipeline.py     # 🚀 оркестратор полной разметки
│   ├── tags.py         # теги
│   └── webhooks.py     # Webhook-подписки
│
├── services/           # Бизнес-логика
│   ├── auto_blur_service.py  # фоновый Auto-blur (люди/номера)
│   ├── behavior_service.py   # эвристики + ML-классификатор
│   ├── bootstrap_service.py  # загрузка стартовых моделей
│   ├── cvat_service.py       # CVAT XML import/export
│   ├── dataset_card_service.py # README.md для датасета
│   ├── ffmpeg_service.py     # работа с видео и ffmpeg
│   ├── file_service.py       # безопасность имен, magic bytes
│   ├── image_service.py      # pHash, IoU, миниатюры, кэши
│   ├── ml_service.py         # YOLO-кэш, batch-инференс
│   ├── model_provider.py     # Provider Pattern (Detector/Pose/Tracker)
│   ├── pipeline_service.py   # 🚀 серверный воркер
│   ├── project_service.py    # purge_projects
│   ├── rate_limiter.py       # защита от спама
│   ├── reid_service.py       # эмбеддинги для трекинга
│   ├── sam_service.py        # SAM-модели
│   ├── settings_service.py   # настройки (TTL и т.д.)
│   ├── stream_service.py     # RTSP-воркеры (OpenCV + YOLO)
│   ├── train_service.py      # подготовка датасетов, ONNX-экспорт
│   ├── trash_service.py      # клинап корзины
│   ├── versioning_service.py # хеширование и Diff версий
│   └── webhook_service.py    # HMAC-подпись и retry
│
├── sdk/                # Python SDK
│   ├── __init__.py
│   ├── client.py       # AsyncDatasetBuilderClient (httpx)
│   └── setup.py        # pip install ./sdk
│
├── js/                 # ES-модули фронтенда
│   ├── main.js         # точка входа, связывает всё
│   ├── api.js          # сетевой слой
│   ├── canvas.js       # логика холста (zoom, pan, рисование)
│   ├── keyboard.js     # горячие клавиши
│   ├── events.js       # Event Delegation
│   ├── store.js        # Reactive State Store (Zustand-like)
│   ├── ui.js           # модалки, диалоги, тултипы
│   ├── theme.js        # темы
│   ├── command_palette.js
│   ├── changelog.js
│   ├── i18n-fallback.js
│   ├── theme-init.js
│   ├── types.js
│   └── utils.js
│
├── tests/              # pytest-тесты
├── data/               # SQLite-БД + app.log        (не в git)
├── models/             # .pt-модели + behavior_clf_*.pkl (не в git)
├── uploads/            # фото датасета              (не в git)
├── videos/             # исходные видео             (не в git)
├── thumbs/             # превью 64×64               (не в git)
├── exports/            # экспорт YOLO/COCO/pose     (не в git)
├── imports/            # временная папка импорта    (не в git)
├── runs/               # результаты обучения        (не в git)
└── backups/            # zip-бэкапы проектов        (не в git)
```

---

## ⌨️ Основные горячие клавиши

| Клавиша | Действие |
|:---|:---|
| <kbd>A</kbd> | Авторазметка текущего кадра |
| <kbd>S</kbd> / <kbd>⌘S</kbd> | Сохранить разметку |
| <kbd>Enter</kbd> | Принять и перейти к следующему |
| <kbd>D</kbd> / <kbd>Delete</kbd> | Удалить выделенные рамки |
| <kbd>C</kbd> | Очистить все рамки |
| <kbd>L</kbd> | Заморозить / разморозить |
| <kbd>M</kbd> | SAM-режим |
| <kbd>⇧K</kbd> | Режим скелета (клик — точка, ПКМ — отмена) |
| <kbd>1</kbd> ... <kbd>6</kbd> | Назначить поведение (eat, walk, lie, drink, stand, active) |
| <kbd>0</kbd> / <kbd>⇧0</kbd> | Присвоить / сбросить animal_id |
| <kbd>N</kbd> / <kbd>P</kbd> | Следующее / предыдущее неразмеченное |
| <kbd>⌘K</kbd> | Командная палитра |
| <kbd>⌘\\</kbd> | Focus-режим |

*(Полный список — в приложении по кнопке `H` или `?`)*

---

## 🧠 Как это работает

### Полный Pipeline
Серверный оркестратор (`services/pipeline_service.py`) выполняет 4 стадии по очереди:
1. **Detect** (YOLOv8) — создает или обновляет рамки.
2. **Pose** (YOLOv8-pose) — ставит скелеты по схеме проекта.
3. **Track** (ByteTrack) — присваивает `animal_id` по видео.
4. **Behavior** — анализирует скелет и движение (эвристика или ML-классификатор).

### Поведение: Эвристика vs ML
- **Эвристика** (bbox-relative) работает из коробки и не требует обучения.
- **ML-классификатор** обучается через кнопку в настройках проекта. Если модель уверена в предсказании более чем на 60%, её ответ имеет приоритет. Обученная модель сохраняется в `models/behavior_clf_project_{id}.pkl` и привязана к конкретному проекту (классу животного).

### RTSP-стримы
При добавлении URL создается фоновый демон, который раз в секунду читает кадр (`cv2.VideoCapture`), прогоняет через YOLO, сохраняет в БД (с флагом `is_stream_frame=True`) и обновляет `animal_id` через простейший IoU-трекер. При перезапуске сервера активные стримы поднимаются автоматически.

### Auto-Blur
При загрузке новых фото (через UI, API, импорт или RTSP) в фоне запускается модель `yolov8n.pt`. Она ищет людей/машины (согласно настройкам проекта) и создает `BlurRegion`. При отдаче картинки через API сервер "на лету" накладывает GaussianBlur. Оригинал на диске остается чистым.

### Кастомные схемы скелета
В настройках проекта можно переопределить дефолтные 17 точек. Эта схема используется при разметке, авто-скелете, экспорте в YOLO-pose / COCO и при обучении pose-модели.

---

## 📝 Лицензия

Этот проект распространяется под лицензией **PolyForm Noncommercial 1.0.0**.

- Физические лица и некоммерческие организации могут использовать его бесплатно.
- Юридические лица (B2B, SaaS, встраивание в продукты) обязаны приобрести коммерческую лицензию.

Подробнее — в файле [LICENSE](LICENSE).

---

## 👤 Автор
**Xulkvan** — [GitHub](https://github.com/Xulkvan) · [DatasetBuilder](https://github.com/Xulkvan/DatasetBuilder)

<div align="center">
**Если проект был полезен — поставь ⭐ на GitHub!**
</div>
