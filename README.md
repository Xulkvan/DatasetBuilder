<div align="center">

# 🤖 DatasetBuilder

**Инструмент для разметки датасетов с авторазметкой на YOLOv8**

От загрузки фото до обученной модели — всё в одном веб-интерфейсе.

[![Version](https://img.shields.io/badge/version-12.4.1-0071e3?style=flat-square)](https://github.com/Xulkvan/DatasetBuilder)
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
2. **Авторазметка** — YOLOv8 рисует рамки сам, ты правишь
3. **Скелет (17 точек)** — разметка позы животного, обучение pose-модели YOLOv8, авто-скелет одним кликом
4. **Поведение** — eat / drink / lie / stand / walk / active: определяется автоматически по геометрии скелета и движению
5. **Трекинг** — ByteTrack присваивает животным постоянные номера, вектор движения на холсте
6. **SAM-сегментация** — точная маска по клику на объекте
7. **Обучение** — детектор и pose-модель прямо из UI, live-графики метрик
8. **Экспорт** — YOLO / COCO / YOLO-pose / COCO-keypoints + CSV атрибутов и треков

Всё работает **локально**: данные остаются на твоём компьютере, никаких облаков.

---

## 🎬 Возможности

### 🖼 Разметка рамок
- **Авторазметка** через YOLOv8 (OpenImages V7 / COCO / свои модели)
- **Два режима авторазметки**: «Добавлять» *(по умолчанию)* и «Заменять»
- **TTA (test-time augmentation)** — точнее на сложных кадрах
- **Debug-режим** (⇧G) — показывает все детекции модели серым пунктиром
- **SAM-сегментация** (M) — точная маска по клику
- **Мультивыбор**, **заморозка** (L), **Undo/Redo** (⌘Z / ⌘Y)
- **Zoom/Pan** — колесо, Ctrl+колесо, pinch, пробел+drag

### 🦴 Скелет (pose)
- **17 точек скелета**: нос, макушка, уши, шея, холка, спина, таз, хвост, колени/копыта (передние и задние)
- **Режим скелета** (⇧K) — клик по холсту ставит следующую точку, правый клик — отмена, двойной — видимость
- **Shift+клик** — точка со скрытой видимостью (для невидимых частей тела)
- **Копирование скелета из похожего кадра** — по pHash + матчинг bbox по IoU
- **Обучение pose-модели YOLOv8** прямо из UI
- **Авто-скелет** — pose-модель размечает все рамки фото одним кликом
- **Экспорт**: YOLO-pose, COCO-keypoints, `keypoints.csv`

### 🧠 Поведение животного
- **6 классов поведения**: eat (ест), drink (пьёт), lie (лежит), stand (стоит), walk (ходит), active (активность)
- **Автоопределение** (🧠 авто) — по геометрии скелета + движению между кадрами
- **Ручная установка** — кнопки в панели или горячие клавиши 1..6
- **Цветные бейджи** на рамках
- **Цветная точка-индикатор** поведения в списке изображений

### 🎯 Номер животного (animal_id)
- **Ручной ввод** номера для рамки
- **Авто-нумерация** — кнопка «+» берёт следующий свободный номер
- **Хоткеи**: `0` — присвоить новый, `Shift+0` — сбросить
- **Массовое применение** — «↧ ко всем» на все рамки фото

### 🎬 Трекинг
- **ByteTrack** — автоматическое присвоение `animal_id` всем свиньям по видео
- **Прогресс** через SSE в реальном времени
- **Работает по кадрам из БД** — оригинальное видео не нужно
- **Ручное связывание** (🔗 с предыдущим) — копирует ID с прошлого кадра по IoU
- **Навигация по треку** (Alt+→ / Alt+←)
- **Панель треков** — список всех треков проекта с превью
- **Плеер трека** — превью-лента кадров одной animal_id
- **Вектор движения** (→ вектор) — стрелка от предыдущего центра bbox к текущему / по центрам скелетов
- **Экспорт треков** в JSON и CSV

### 📦 Импорт / Экспорт
- **Импорт**: zip с картинками + разметкой (автодетект формата)
- **4 формата разметки**: COCO JSON, YOLO TXT, CVAT XML, Label Studio JSON
- **Внешние источники**: Roboflow, Supervisely, Labelbox, Scale AI, V7 Darwin, URL, локальная папка
- **pHash-дедупликация** — одинаковые фото отсеиваются
- **Экспорт YOLO / COCO** — с автоматическим переходом на pose-формат
- **CSV-экспорт**: статистики, списка файлов, всех рамок
- **Бэкап проекта** — zip с фото + разметкой + тегами + скелетами

### 🎥 Видео
- **Извлечение кадров** через ffmpeg (mp4 / mov / avi / mkv / webm)
- FPS: 0.5 / 1 / 2 / 5 / 10
- **Таймкод кадра** (`timestamp_sec`) рассчитывается автоматически
- Автопоиск ffmpeg + ручное указание пути + справка под ОС

### 🤖 Обучение
- **Два режима**: детектор (bbox) и **pose** (скелет)
- **Fine-tune YOLOv8** (nano / small / medium) из UI
- **Live-прогресс** через SSE + графики mAP/loss
- **Сравнение моделей** — side-by-side метрики двух прогонов
- **Автоактивация** новой модели после обучения
- **Остановка с сохранением** `last.pt` → `<name>_partial.pt`
- **Active learning** — подсказывает, когда переобучить модель

### 🎨 Организация
- **Мультиклассовые проекты**
- **Теги** — цветные метки с фильтром
- **Корзина** — мягкое удаление с per-project TTL
- **Фильтры**: неразмеченные / low-conf / сложные / дубликаты
- **Сортировка**: имя (natural sort) / тип / уверенность / дата / размер
- **Виртуальный скролл** — 100k+ фото без тормозов
- **Секции** «Неразмеченные / Размеченные» с автосворачиванием
- **Drag-n-drop изображений** между проектами

### 🛠 Инструменты
- **Валидатор разметки** — маленькие, вложенные, наложение, out-of-bounds
- **Статистика** — распределение по уверенности, топ-10 сомнительных
- **Поиск дубликатов** (Multi-Index Hashing LSH)
- **Bulk rename** по маске
- **Перемещение / копирование** между проектами
- **«Показать на диске»**
- **История статусов** — лог на 1000 событий
- **Миграция MySQL → SQLite** одной кнопкой

### 🎨 Интерфейс
- **Apple HIG-inspired** дизайн — Liquid Glass, spring-анимации, haptics
- **Тёмная / светлая / авто** тема
- **Русский / English** интерфейс
- **Focus-режим** (⌘\\)
- **Command palette** (⌘K)
- **Горячие клавиши** — от `A` до `?`
- **Reduce Motion**

### ⚡ Производительность & Архитектура
- **Batch-инференс (V12.4.0)** — пакетная авторазметка ускоряет работу в 3-5 раз на GPU (на CPU автоматически подстраивается под память).
- **Модульный бэкенд (V12.x)** — монолит разделён на `routers/` (эндпоинты) и `services/` (бизнес-логика).
- **Zustand-like State Store** — реактивное состояние, синхронизация через Proxy (`js/store.js`).
- **rAF-батчинг рендера** — серия обновлений склеивается в 1 кадр.
- **Безопасное снятие выделения** — capture-фаза на `pointerdown` с прямым очищением DOM.
- **Виртуальный скролл**, **Кэш YOLO** на 2 модели (LRU), **Фоновый warmup**.
- **Безопасные коммиты в БД (V12.x)** — защита SQLite от `database is locked` в фоновых потоках трекинга и обучения.

### 🔒 Безопасность
- **CSRF** — заголовок `X-Requested-With` на write-запросах
- **CSP** — `default-src 'self'`, `frame-ancestors 'none'`
- **X-Frame-Options: DENY**, **X-Content-Type-Options: nosniff**
- **Zip-slip / path traversal protection**
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

---

## 🗂 Структура проекта

```text
DatasetBuilder/
├── app.py              # FastAPI backend (сборка роутеров и middleware)
├── run.py              # точка входа (dev)
├── launcher.py         # desktop-обёртка (pywebview)
├── security.py         # CSRF + CSP middleware
├── config.py           # Единый источник констант (пороги, лимиты, схемы)
├── database.py         # Настройка SQLAlchemy (engine, session)
├── models.py           # ORM-модели (Project, ImageModel, Annotation и др.)
├── schemas.py          # Pydantic-схемы валидации
├── logger.py           # Кастомный логгер статусов в памяти
├── version.py          # единый источник версии
├── build.spec          # PyInstaller spec
├── index.html          # UI
├── style.css           # стили
├── i18n.js             # словари ru/en
├── requirements.txt
├── .env.example
├── icon.ico / .icns / .png
├── LICENSE
├── README.md
│
├── routers/            # Эндпоинты API (разделены по доменам)
│   ├── images.py       # CRUD, загрузка, разметка
│   ├── ml.py           # авторазметка, SAM, классы
│   ├── projects.py     # проекты, корзина, настройки
│   ├── system.py       # логи, версии
│   └── tags.py         # теги
│
├── services/           # Бизнес-логика (вынесена из app.py)
│   ├── behavior_service.py   # predict_behavior, геометрия
│   ├── bootstrap_service.py  # загрузка стартовых моделей
│   ├── ffmpeg_service.py     # работа с видео и ffmpeg
│   ├── file_service.py       # безопасность имен, magic bytes
│   ├── image_service.py      # pHash, IoU, миниатюры, кэши
│   ├── ml_service.py         # YOLO-кэш, batch-инференс
│   ├── project_service.py    # purge_projects
│   ├── rate_limiter.py       # защита от спама
│   ├── sam_service.py        # SAM-модели
│   ├── settings_service.py   # настройки (TTL и т.д.)
│   ├── train_service.py      # подготовка датасетов
│   └── trash_service.py      # клинап корзины
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
├── data/               # SQLite-БД + app.log        (не в git)
├── models/             # .pt-модели                 (не в git)
├── uploads/            # фото датасета              (не в git)
├── videos/             # исходные видео             (не в git)
├── thumbs/             # превью 64×64               (не в git)
├── exports/            # экспорт YOLO/COCO/pose     (не в git)
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
| <kbd>L</kbd> | Заморозить / разморозить |
| <kbd>M</kbd> | SAM-режим |
| <kbd>Z</kbd> | Zoom к выделенной рамке |
| <kbd>⌘Z</kbd> / <kbd>⌘Y</kbd> | Отменить / повторить |
| <kbd>⇧⌘Z</kbd> | Undo/Redo списка |

### Скелет (Shift+K)

| Клавиша | Действие |
|:---|:---|
| <kbd>⇧K</kbd> | Вкл/выкл режим скелета |
| Клик | Поставить следующую точку |
| <kbd>⇧</kbd> + клик | Точка со скрытой видимостью |
| Правый клик | Удалить последнюю точку |
| Двойной клик | Переключить видимость точки |

### Поведение и ID

| Клавиша | Действие |
|:---|:---|
| <kbd>1</kbd> | Ест |
| <kbd>2</kbd> | Ходит |
| <kbd>3</kbd> | Лежит |
| <kbd>4</kbd> | Пьёт |
| <kbd>5</kbd> | Стоит |
| <kbd>6</kbd> | Активность |
| <kbd>0</kbd> | Присвоить новый animal_id |
| <kbd>⇧0</kbd> | Сбросить animal_id |

### Трекинг

| Клавиша | Действие |
|:---|:---|
| <kbd>Alt</kbd>+<kbd>→</kbd> | Следующий кадр того же трека |
| <kbd>Alt</kbd>+<kbd>←</kbd> | Предыдущий кадр того же трека |

### Навигация

| Клавиша | Действие |
|:---|:---|
| <kbd>N</kbd> / <kbd>P</kbd> | Следующее / предыдущее неразмеченное |
| <kbd>←</kbd> <kbd>→</kbd> | Листать изображения / двигать рамку |
| <kbd>⇧</kbd> + стрелки | Ресайзить выделенную рамку |

### Холст

| Клавиша | Действие |
|:---|:---|
| <kbd>Ctrl</kbd> + колесо | Zoom |
| Колесо | Скролл страницы |
| <kbd>Пробел</kbd> + drag | Панорамирование |
| <kbd>⇧</kbd> + drag | Рисовать рамку при zoom > 1 |
| <kbd>+</kbd> / <kbd>−</kbd> / <kbd>0</kbd> | Zoom in / out / сброс |

### Прочее

| Клавиша | Действие |
|:---|:---|
| <kbd>⌘K</kbd> | Командная палитра |
| <kbd>⌘\\</kbd> | Focus-режим |
| <kbd>⇧G</kbd> | Debug-режим YOLO |
| <kbd>H</kbd> / <kbd>?</kbd> | Все горячие клавиши |
| <kbd>Esc</kbd> | Снять выделение / закрыть модалку |

---

## 🧠 Как это работает

### Авторазметка (детектор)
YOLOv8 обрабатывает кадр, оставляет только детекции класса проекта, дедуплицирует по IoU > 0.5, сохраняет в БД.

**Режимы:**
- **Добавлять** *(дефолт)* — существующие рамки сохраняются
- **Заменять** — вся не-замороженная разметка стирается

### Пакетная авторазметка (Batch)
В версии V12.4.0 добавлен Batch-инференс. Изображения отправляются в модель пачками (chunk'ами). На GPU размер пачки достигает 16 штук, что даёт прирост скорости до 5 раз. На CPU размер автоматически снижается для экономии RAM.

### Скелет и pose-модель
- **17 точек** на животное
- **Режим разметки** вручную или копированием с похожего кадра
- **Обучение** pose-модели YOLOv8 из UI (`yolo pose train`)
- **Экспорт** в YOLO-pose и COCO-keypoints форматы

### Поведение
Правило по геометрии скелета + движению:
- **drink** — нос у дна кадра
- **eat** — нос ниже середины спина↔копыта ИЛИ голова наклонена
- **walk** — смещение bbox > 0.02 между кадрами
- **active** — смещение bbox > 0.06
- **lie** — копыта близко к спине (offset < 0.30)
- **stand** — копыта далеко (offset ≥ 0.30)

### Трекинг (ByteTrack)
1. Собираются все кадры одного `video_id` по `frame_index`
2. Прогон через ByteTrack (`model.track(... persist=True)`)
3. Маппинг `track_id → animal_id`: если у рамки уже был ID — он используется
4. `animal_id` присваивается всем аннотациям трека

### Архитектура фронтенда
- **State Store**: единый объект `window.AppState`, Proxy-listeners.
- **Event Delegation**: `data-action` вместо inline-onclick (CSP compliance).
- **Capture-фаза для deselect**: глобальный `pointerdown` на `document` снимает выделение при клике мимо рамки, игнорируя интерактивные элементы.
- **Модульность**: логика разделена на `js/*.js` файлы, точка сборки — `js/main.js`.

---

## ❓ FAQ

**Где хранятся фото и разметка?**
См. секцию «Где хранятся данные». Всё локально.

**Работает без видеокарты?**
Да, всё на CPU. Обучение медленнее, авторазметка — быстро.

**Как перенести на другой компьютер?**
Бэкап (Настройки → Сделать бэкап) + `uploads/`. Или скопируй всю `DATA_ROOT`.

**Сколько фото нужно для обучения?**
- **Детектор**: минимум 30–50 размеченных рамок, лучше 200+
- **Pose-модель**: минимум 30 скелетов, лучше 100+

**Почему у ручной рамки нет вектора движения?**
Вектор — это смещение между двумя кадрами. Если рамка только что появилась и нет предыдущего кадра с этой же свиньёй — вектора физически нет.

**Не работает Ctrl+Z**
Пофикшено (проксирование состояния в `window`).

**Не снимается выделение при клике мимо**
Пофикшено (используется capture-фаза `pointerdown` на `document` + прямая очистка DOM).

---

## 🤝 Contributing

PR и issue приветствуются.

```bash
git checkout -b feature/my-feature
git commit -m "feat: my feature"
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
- Проект: [DatasetBuilder](https://github.com/Xulkvan/DatasetBuilder)

---

<div align="center">

**Если проект был полезен — поставь ⭐ на GitHub!**

</div>