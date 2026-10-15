<div align="center">

# 🤖 DatasetBuilder

**Инструмент для разметки датасетов с авторазметкой на YOLOv8**

От загрузки фото до обученной модели — всё в одном веб-интерфейсе.

[![Version](https://img.shields.io/badge/version-10.4.0-0071e3?style=flat-square)](https://github.com/Xulkvan/DatasetBuilder)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLite | MySQL](https://img.shields.io/badge/DB-SQLite%20%7C%20MySQL-4479A1?style=flat-square)]()
[![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-FF6B35?style=flat-square)](https://github.com/ultralytics/ultralytics)
[![License](https://img.shields.io/badge/license-MIT-34c759?style=flat-square)](LICENSE)

</div>

---

## ✨ Что это

**DatasetBuilder** — веб-приложение для быстрой разметки датасетов с полным циклом:

1. **Загрузка** фото, видео или импорт готового датасета (COCO / YOLO / CVAT / Label Studio / Roboflow / Supervisely / Labelbox / Scale AI / V7 Darwin)
2. **Авторазметка** нейросетью — YOLOv8 рисует рамки, ты только правишь
3. **SAM-сегментация** в один клик — точная маска по клику на объекте
4. **Обучение** — когда накопилось 30+ размеченных кадров, обучаешь свою модель прямо из UI
5. **Экспорт** — YOLO или COCO с автоматическим train/val/test split

Всё работает **локально**: данные остаются на твоём компьютере, никаких облаков.

---

## 🎬 Возможности

### 🖼 Разметка
- **Авторазметка** через YOLOv8 (OpenImages V7 / COCO / свои модели)
- **Два режима авторазметки**:
  - **«Добавлять»** *(по умолчанию)* — старые рамки не сбрасываются, дорисовываются только уникальные детекции
  - **«Заменять»** — старая разметка (кроме замороженных) стирается
- **TTA (test-time augmentation)** — точнее на сложных кадрах (~2× медленнее)
- **Debug-режим** (⇧G) — показывает все детекции модели серым пунктиром
- **SAM-сегментация** (M) — точная маска по клику, кэш эмбеддинга картинки
- **Мультивыбор** рамок (Shift+клик), групповое перемещение
- **Заморозка** рамок (L) — защита от перезаписи при авторазметке
- **Undo/Redo**:
  - для рамок — ⌘Z / ⌘Y (50 шагов), включая откат авторазметки
  - для списка изображений — ⇧⌘Z (восстановление удалённых)
- **Zoom/Pan** холста — колесо, pinch, пробел+drag

### 📦 Импорт / Экспорт
- **Импорт целиком**: zip с картинками + разметкой (автодетект формата)
- **4 формата**: COCO JSON, YOLO TXT, CVAT XML, Label Studio JSON
- **Внешние источники**: Roboflow, Supervisely, Labelbox, Scale AI, V7 Darwin, URL, локальная папка
- **pHash-дедупликация** — одинаковые фото отсеиваются автоматически
- **Экспорт** YOLO / COCO с разбиением 70/20/10, 80/20, 85/10/5 или без split
- **CSV-экспорт**: статистики (с учётом фильтров), списка файлов и **всех рамок** проекта
- **Бэкап проекта** — zip с фото + разметкой + тегами

### 🎥 Видео
- **Извлечение кадров** через ffmpeg (mp4 / mov / avi / mkv / webm)
- FPS: 0.5 / 1 / 2 / 5 / 10
- Автопоиск ffmpeg в PATH, WinGet, `/usr/local/bin`, `~/.local/bin`
- Ручное указание пути + справка по установке под каждую ОС

### 🤖 Обучение
- **Fine-tune** YOLOv8 (nano / small / medium) прямо из UI
- **Continual learning** — дообучение активной модели
- **Live-прогресс** через SSE — видно каждую эпоху и loss
- **Live-графики** mAP/loss в реальном времени
- **Сравнение моделей** — side-by-side метрики двух прогонов
- **Автоактивация** новой модели после обучения
- **Остановка с сохранением** `last.pt` → `<name>_partial.pt`
- **Метрики**: mAP@50, mAP@50-95, precision/recall, confusion matrix, val predictions
- **Active learning** — подсказывает, когда переобучить модель

### 🎨 Организация
- **Мультиклассовые проекты** — у каждого свой объект детекции
- **Поиск по классам** активной YOLO-модели
- **Теги** — цветные метки с фильтром
- **Корзина** — мягкое удаление с per-project TTL
- **Фильтры** — неразмеченные / low-conf / сложные / дубликаты
- **Сортировка** — имя (natural sort) / тип / уверенность / дата / размер
- **Виртуальный скролл** — 100k+ фото без тормозов
- **Секции** «Неразмеченные / Размеченные» с автосворачиванием
- **Drag-n-drop изображений** между проектами в сайдбаре

### 🛠 Инструменты
- **Валидатор разметки** — маленькие, вложенные, наложение, out-of-bounds
- **Статистика** — распределение по уверенности, топ-10 сомнительных
- **Похожие кадры** — pHash + копирование разметки
- **Поиск дубликатов** — группы, выбор «оставить»
- **Bulk rename** по маске `image_{n:04d}`
- **Перемещение / копирование** между проектами
- **«Показать на диске»** — открывает проводник/Finder с выделенным файлом
- **История статусов** — in-memory лог на 1000 событий
- **Миграция MySQL → SQLite** одной кнопкой (с откатом `.env` при ошибке)
- **Хранилище** — размеры по папкам, скачивание БД одним кликом

### 🎨 Интерфейс
- **Apple HIG-inspired** дизайн — Liquid Glass, spring-анимации, haptics
- **Тёмная / светлая / авто** тема
- **Русский / English** интерфейс (i18n через data-атрибуты)
- **Focus-режим** (⌘\\)
- **Command palette** (⌘K) — все действия, классы, теги, недавние команды
- **Тонкая настройка под тач** — крупные хендлы, увеличенные чекбоксы
- **Горячие клавиши** — от `A` до `?`
- **Кастомные тултипы**, скелетоны, материализация модалок
- **Reduce Motion** — уважение к `prefers-reduced-motion`

### 🔒 Безопасность
- **CSRF-защита** — кастомный заголовок `X-Requested-With` на всех write-запросах
- **CSP** — `default-src 'self'`, `frame-ancestors 'none'`
- **X-Frame-Options: DENY**, **X-Content-Type-Options: nosniff**
- **Referrer-Policy: no-referrer**, **Permissions-Policy**
- **Zip-slip protection** при распаковке архивов
- **Path traversal protection** для всех файловых операций
- **Rate limiting** на upload / import / autolabel / train / SAM

---

## 🚀 Быстрый старт

### Требования

- **Python 3.10+**
- **MySQL 8.0+** *(опционально — по умолчанию SQLite)*
- **FFmpeg** *(опционально — для видео)*
- ОС: Windows 10+ / macOS 11+ / Linux

### Вариант 1: SQLite (рекомендуется)

```bash
git clone https://github.com/Xulkvan/PigDatasetBuilder.git
cd PigDatasetBuilder

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

При первом запуске автоматически скачается `yolov8n-oiv7.pt` (7 МБ).

### Вариант 3: Desktop (.exe / .app / .AppImage)

```bash
pip install pyinstaller
pyinstaller build.spec
# → dist/DatasetBuilder/
```



---

## ⚙️ Настройка

Все параметры через `.env` (см. `.env.example` как шаблон):

```env
# БД
DB_ENGINE=sqlite | mysql
DB_PATH=data/dataset.db                                # SQLite
DB_USER / DB_PASSWORD / DB_HOST / DB_PORT / DB_NAME    # MySQL

# Данные (по умолчанию — системная папка ОС)
DATA_ROOT=/custom/path

# Сервер
HOST=127.0.0.1
PORT=8000
DEBUG=0

# Лимиты
MAX_UPLOAD_MB=50
MAX_IMPORT_MB=2048
MAX_VIDEO_MB=2048
MAX_VIDEO_FRAMES=3000
MAX_EXTRACTED_MB=10240
```

**Где хранятся данные** (по умолчанию — `DATA_ROOT`):
- **Windows:** `%LOCALAPPDATA%\DatasetBuilder`
- **macOS:** `~/Library/Application Support/DatasetBuilder`
- **Linux:** `~/.local/share/DatasetBuilder`

В `dev`-режиме (`python run.py`) всё пишется в папку проекта.

---

## 🗂 Структура проекта

```text
PigDatasetBuilder/
├── app.py              # FastAPI backend
├── run.py              # точка входа (dev, с reload)
├── launcher.py         # desktop-обёртка (pywebview)
├── security.py         # CSRF + CSP middleware
├── version.py          # единый источник версии
├── build.spec          # PyInstaller spec
├── index.html          # UI
├── style.css           # стили
├── app.js              # фронтенд-логика
├── i18n.js             # словари ru/en
├── requirements.txt
├── .env.example
├── icon.ico
├── icon.icns
├── icon.png
├── LICENSE
└── README.md

├── data/               # SQLite-БД + app.log        (не в git)
├── models/             # .pt-модели                 (не в git)
├── uploads/            # фото датасета              (не в git)
├── videos/             # исходные видео             (не в git)
├── thumbs/             # превью 64×64               (не в git)
├── exports/            # экспорт YOLO/COCO          (не в git)
├── imports/            # временная папка импорта    (не в git)
├── runs/               # результаты обучения        (не в git)
└── backups/            # zip-бэкапы проектов        (не в git)
```

---

## ⌨️ Горячие клавиши

### Разметка

| Клавиша | Действие |
|:---|:---|
| <kbd>A</kbd> | Авторазметка текущего кадра |
| <kbd>R</kbd> | Перезапустить авторазметку |
| <kbd>S</kbd> / <kbd>⌘S</kbd> | Сохранить разметку |
| <kbd>Enter</kbd> | Принять и перейти к следующему неразмеченному |
| <kbd>D</kbd> / <kbd>Delete</kbd> | Удалить выделенные рамки |
| <kbd>C</kbd> | Очистить все рамки |
| <kbd>F</kbd> | Пометить как «сложный» |
| <kbd>L</kbd> | Заморозить / разморозить выделенные |
| <kbd>M</kbd> | SAM-режим |
| <kbd>Z</kbd> | Zoom к выделенной рамке |
| <kbd>⌘Z</kbd> / <kbd>⌘Y</kbd> | Отменить / повторить (включая откат авторазметки) |
| <kbd>⇧⌘Z</kbd> | Undo/Redo списка (восстановить удалённые) |

### Навигация

| Клавиша | Действие |
|:---|:---|
| <kbd>N</kbd> / <kbd>P</kbd> | Следующее / предыдущее неразмеченное |
| <kbd>←</kbd> <kbd>→</kbd> | Листать изображения / двигать рамку |
| <kbd>⇧</kbd> + стрелки | Ресайзить выделенную рамку |

### Холст

| Клавиша | Действие |
|:---|:---|
| Колесо / pinch | Zoom |
| <kbd>Пробел</kbd> + drag | Панорамирование |
| <kbd>⇧</kbd> + drag | Рисовать рамку при zoom > 1 |
| <kbd>+</kbd> / <kbd>−</kbd> | Zoom in / out |
| <kbd>0</kbd> | Сбросить zoom |

### Прочее

| Клавиша | Действие |
|:---|:---|
| <kbd>⌘K</kbd> | Командная палитра |
| <kbd>⌘\\</kbd> | Focus-режим (скрыть сайдбар) |
| <kbd>⇧G</kbd> | Debug-режим YOLO |
| <kbd>H</kbd> / <kbd>?</kbd> | Все горячие клавиши |
| <kbd>Esc</kbd> | Снять выделение / закрыть модалку |

---

## 🧠 Как это работает

### Авторазметка
YOLOv8 обрабатывает кадр, оставляет только детекции класса проекта, дедуплицирует по IoU > 0.5, сохраняет в БД.

**Режимы (настройки → Авторазметка):**
- **Добавлять** *(дефолт)* — существующие рамки сохраняются, новые детекции добавляются только если не дублируют старые (фильтр по IoU > 0.5 **или** расстоянию центров < 5%). Работает в одиночной / debug / batch авторазметке.
- **Заменять** — вся не-замороженная разметка стирается, рисуются только детекции модели.

### SAM
`mobile_sam.pt` (или SAM2). Первый клик по картинке — encoder + decoder (~1–2 с), последующие клики по **той же** картинке — только decoder (~100–200 мс). Эмбеддинг кэшируется в `predictor`.

### pHash-дедупликация
Perceptual hash через DCT (64 бита). Поиск дубликатов **по бакетам** (6 hex-символов, лимит 400 на бакет — защита от O(n²)). Порог Hamming ≤ 6.

### Обучение
1. Размеченные изображения копируются в `runs/train_<ts>/dataset/`
2. Split **85% train / 15% val** (детерминированно, `seed=42`)
3. `yolo detect train` с `freeze=8`, `lr0=0.001`, `cos_lr=True`
4. Прогресс стримится в UI через SSE — видна каждая эпоха
5. По завершении `best.pt` копируется в `models/` и активируется

### Миграция MySQL → SQLite
Копирование через ORM по таблицам в правильном порядке (settings → projects → videos → images → tags → annotations → image_tags). Проверка количества строк после каждой таблицы. **Снимок `.env` перед началом** и откат при ошибке.

### Бэкап проекта
Один zip содержит:
- `meta.json` — версия, дата, количество
- `images_index.json` — метаданные фото
- `annotations.json` — все рамки по `image_id`
- `tags.json` — теги и привязки
- `images/<id>.jpg` — сами фото

---

## 🛠 Технологии

| Слой | Стек |
|:---|:---|
| **Backend** | FastAPI, Uvicorn, SQLAlchemy 2.0, Pydantic 2 |
| **БД** | SQLite (WAL) / MySQL 8 (utf8mb4) |
| **ML** | Ultralytics YOLOv8, SAM, Pillow, NumPy |
| **Frontend** | Vanilla JS (ES2020), CSS3 (backdrop-filter, Grid) |
| **Real-time** | Server-Sent Events |
| **Desktop** | pywebview |
| **Безопасность** | CSRF, CSP, X-Frame, nosniff (свой middleware) |

**Без** React / Vue / Tailwind / jQuery — весь UI на чистом JS + CSS.

---

## ❓ FAQ

**Где хранятся фото и разметка?**
См. секцию «Где хранятся данные». Всё локально, ничего не уходит в облако.

**Работает без видеокарты?**
Да, всё на CPU. Обучение медленнее, авторазметка — быстро.

**Как перенести на другой компьютер?**
Настройки → Сделать бэкап (получишь zip) + скопируй папку `DATA_ROOT`. Или просто скопируй всю `DATA_ROOT` целиком.

**Сколько фото нужно для обучения?**
Минимум 30–50 размеченных. Для стабильного результата — 200+.

**Работает на телефоне / планшете?**
Да, поддерживает тач (pinch-zoom, панорамирование двумя пальцами, крупные хендлы). Но интерфейс оптимизирован под десктоп.

**Как перейти на SQLite?**
Настройки → Хранилище → Мигрировать на SQLite. Существующая MySQL-БД не трогается.

**Почему 403 при запросе к API?**
С V8.1.0 включена CSRF-защита: все write-запросы (POST/PATCH/DELETE/PUT) требуют заголовок `X-Requested-With: DatasetBuilder`. Из UI всё работает автоматически. Если пишешь свой клиент — добавь заголовок.

**Авторазметка стирает мою ручную разметку!**
С V8.2.0 дефолтный режим — **«Добавлять»** (ручные рамки сохраняются). Если хочешь старое поведение — Настройки → Авторазметка → «Заменять».

**Ctrl+Z не откатывает авторазметку**
Пофикшено в V8.2.2. Если не работает — обнови приложение (Ctrl+Shift+R).

---

## 🤝 Contributing

PR и issue приветствуются. Если нашёл баг — открывай issue на GitHub.

```bash
# форк → клонируй → создай ветку
git checkout -b feature/my-feature
# кодь → коммить → пуш
git push origin feature/my-feature
# → открой Pull Request
```

---

## 📝 Лицензия

MIT — используй свободно, в том числе в коммерческих проектах.

---

## 👤 Автор

**Xulkvan**

- GitHub: [@Xulkvan](https://github.com/Xulkvan)
- Проект: [PigDatasetBuilder](https://github.com/Xulkvan/PigDatasetBuilder)

---

<div align="center">

**Если проект был полезен — поставь ⭐ на GitHub!**

</div>
