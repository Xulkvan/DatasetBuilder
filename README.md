<div align="center">

# 🤖 DatasetBuilder

**Инструмент для разметки датасетов с авторазметкой на YOLOv8 / YOLO11**

От загрузки фото до обученной модели и готового B2B API — всё в одном веб-интерфейсе. Локально или в команде.

[![Version](https://img.shields.io/badge/version-14.4.6-0071e3?style=flat-square)](https://github.com/Xulkvan/DatasetBuilder)
[![Python](https://img.shields.io/badge/python-3.13%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLite | MySQL | PostgreSQL](https://img.shields.io/badge/DB-SQLite%20%7C%20MySQL%20%7C%20PostgreSQL-4479A1?style=flat-square)]()
[![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-FF6B35?style=flat-square)](https://github.com/ultralytics/ultralytics)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue?style=flat-square)](LICENSE)

</div>

---

## ✨ Что это

**DatasetBuilder** — веб-приложение и B2B-платформа для быстрой разметки датасетов с полным циклом. Работает как в локальном режиме (один пользователь, SQLite), так и в командном режиме (Team Edition с PostgreSQL, ролями и назначением задач).

0. **🚀 Full Pipeline** — нажатие одной кнопки прогоняет весь проект по 4 этапам (рамки → скелеты → треки → поведение) и выдает готовый датасет.
1. **Загрузка** фото, RTSP-потоков, видео или импорт готового датасета (COCO / YOLO / CVAT / Label Studio / Roboflow / Supervisely / Labelbox / Scale AI / V7 Darwin).
2. **Авторазметка** — YOLOv8 рисует рамки сам, ты правишь.
3. **Скелет (17 точек)** — разметка позы животного, обучение pose-модели YOLOv8, авто-скелет одним кликом, **кастомные схемы скелета**.
4. **Поведение** — эвристика по геометрии или **ML-классификатор** (RandomForest), обученный на ваших данных.
5. **Трекинг** — ByteTrack присваивает животным постоянные номера, вектор движения на холсте.
6. **SAM-сегментация** — точная маска по клику на объекте.
7. **MLOps** — экспорт в **ONNX**, **Data Versioning (Diff)**, **Active Learning**, **Webhooks**, **Auto-Blur** приватных зон.
8. **Обучение** — детектор и pose-модель прямо из UI, live-графики метрик.
9. **Командная работа (Team Edition)** — роли (Admin, Manager, Annotator, Reviewer), назначение задач, блокировка кадров от одновременного редактирования, управление пользователями.
10. **Edge Runtime** — выгрузка модели на NVIDIA Jetson для real-time инференса по RTSP без основного сервера.
11. **Валидатор разметки** — автоматический поиск мелких, вложенных, выходящих за границы рамок, размытых кадров и окклюзированных точек скелета.
12. **Экспорт** — YOLO / COCO / YOLO-pose / COCO-keypoints, а также **Parquet**, **SQL**, **CVAT XML** и CSV атрибутов.

Всё работает **локально**: данные остаются на твоём компьютере, никаких облаков. Для B2B-интеграций доступен **Async SDK**, **API v2** и **Webhooks**. Есть **headless CLI** для запуска пайплайна без веб-интерфейса.

---

## 🎬 Возможности

### 👥 Team Edition (Командная работа)
- **Безопасная авторизация**: Вход по логину и паролю с использованием HttpOnly Cookie (без уязвимых JWT в localStorage).
- **4 роли**: 
  - **Admin**: Полный доступ, управление пользователями и настройками сервера.
  - **Manager**: Создание проектов, назначение задач, обучение моделей, экспорт.
  - **Annotator**: Разметка только назначенных кадров, без доступа к удалению или экспорту.
  - **Reviewer**: Проверка разметки, одобрение (Approve) или возврат на доработку (Reject).
- **Управление пользователями**: Admin создаёт сотрудников с временным паролем (модалка «Пользователи» в шапке), удаляет уволенных, меняет роли. Последнего admin'а удалить нельзя — защита от блокировки системы.
- **Смена пароля**: в профиле или принудительно при первом входе (флаг `must_change_password`).
- **Матрица прав с сервера**: `/api/auth/status` отдаёт `permissions: [...]` для текущей роли. Интерфейс не «прыгает» после загрузки и сразу скрывает недоступные кнопки. Источник правды — `config.ROLE_PERMISSIONS`.
- **Защита от brute-force**: лимит на IP (20 попыток за 5 мин) и на username (5 попыток за 5 мин).
- **Назначение задач (Assign)**: Менеджер выделяет кадры и назначает их на конкретного сотрудника (или поровну между несколькими). Разметчики видят только свои задачи (фильтр «Мои задачи»).
- **Статусы кадров**: unassigned → assigned → in_progress → review → approved / rejected. Разметчик отправляет на проверку (Submit), Reviewer одобряет или возвращает с комментарием.
- **Блокировка кадров (Soft Locks)**: Если кадр открыт одним пользователем, другой видит плашку «Кадр редактирует Иван» и не может вносить изменения (защита от перезаписи).
- **Аудит действий**: В «Историю статусов» записывается ID и логин пользователя, совершившего действие (кто удалил фото, кто обучил модель). Фильтр по пользователю.
- **Первичная настройка (Setup Wizard)**: При первом запуске базы данных приложение попросит создать аккаунт Администратора.
- **Локальный режим (Local Mode)**: При использовании SQLite вход не требуется, всё работает как раньше (скрытый SuperAdmin).

### 📦 Edge Runtime (NVIDIA Jetson)
- **Готовый Docker-образ**: Пакет для развертывания обученной модели на Edge-устройствах (NVIDIA Jetson / JetPack 5.x).
- **Скачивание из UI**: В меню любой модели есть кнопка «Скачать Edge-пакет». Вы получаете ZIP-архив с `model.onnx`, `edge_server.py` и `Dockerfile`.
- **Real-time RTSP**: Сервер на базе FastAPI + ONNX Runtime подключается к камере по RTSP и отдает JSON-события (координаты рамок, уверенность) без задержек.
- **API Edge-сервера**: `/health` (статус), `/stream/start` (запуск), `/events` (последние события), `/events/stream` (SSE-поток).
- **Формат событий**: `{"ts": 1730123456.789, "detections": [{"class_id": 0, "confidence": 0.87, "bbox": [0.1, 0.2, 0.3, 0.4]}]}`.

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
- Простейший IoU-трекер + кросс-камерный ReID на лету для стримов (выдача `animal_id`).
- Управление через модалку «RTSP-стримы» (добавить, остановить, статус). Лимит одновременных стримов — 2 на проект.

### 🔌 API v2 и Python SDK (B2B)
- **REST API** с Bearer-авторизацией (`API_KEY`).
- **Swagger документация**: `/api/docs` и `/api/redoc` с тегами.
- **Фоновые задачи**: async autolabel с поллингом статуса.
- **Универсальный экспорт**: `GET /api/v2/projects/{id}/export?format=yolo|yolo_pose|coco|parquet` — отдаёт `download_url`.
- **Rate limiting** на тяжёлые операции (upload, autolabel, train).
- **Python SDK**: `pip install ./sdk` — асинхронный клиент (`AsyncDatasetBuilderClient`) на базе `httpx` с методами `upload_batch`, `get_dataset_coco`, `start_training`.

### 🕸 Webhooks (Интеграции)
- **Подписки на события**: `annotation.saved`, `training.completed`, `dataset.exported`.
- **HMAC-SHA256 подпись**: заголовок `X-DatasetBuilder-Signature` — получатель может проверить, что запрос пришёл от вашего сервера.
- **Retry-логика**: до 3 попыток с exponential backoff (1s, 2s, 4s) — временные падения получателя не теряют события.
- **Асинхронно**: доставка идёт в фоновом потоке, ответ пользователю не блокируется (даже если получатель лежит).
- **Кнопка «🔔» в тулбаре** + CRUD-модалка: добавить URL + выбрать событие + указать secret_key, удалить подписку, отправить тестовое событие.
- **SSRF-защита**: вебхук на `localhost` / приватный IP блокируется (настраивается через `WEBHOOK_ALLOW_PRIVATE`).

### 🖼 Разметка рамок
- **Авторазметка** через YOLOv8 (OpenImages V7 / COCO / свои модели).
- **TTA (test-time augmentation)**, **Debug-режим** (⇧G), **SAM-сегментация** (M).
- **Мультивыбор**, **заморозка** (L), **Undo/Redo** (⌘Z / ⌘Y).
- **Zoom/Pan** — колесо, Ctrl+колесо, pinch, пробел+drag.
- **Режим «Добавлять / Заменять»** — при повторной авторазметке можно сохранить старые рамки или стереть (кроме замороженных).

### 🦴 Скелет (Pose) и Кастомные схемы
- **17 точек скелета** по умолчанию.
- **Кастомные схемы**: в настройках проекта можно задать свои точки и их иерархию (table-editor).
- **Режим скелета** (⇧K) — клик ставит точку, правый клик отменяет, двойной — видимость.
- **Обучение pose-модели YOLOv8** прямо из UI.
- **Авто-скелет** — pose-модель размечает все рамки фото.
- **Копирование скелета** с похожего кадра (кнопка «🦴 из похожего» — матчинг по IoU).
- **Экспорт** учитывает кастомные схемы (YOLO-pose, COCO-keypoints).

### 🧠 Поведение животного
- **6 классов**: eat, drink, lie, stand, walk, active.
- **Эвристика (bbox-relative)** — пороги привязаны к рамке, а не к кадру. Есть Grid Search калибровка.
- **ML-классификатор**: обучение RandomForest на ваших скелетах (в настройках проекта). Если классификатор уверен (>60%), он перебивает эвристику. Файлы хранятся per-project (`models/behavior_clf_project_{id}.pkl` + `.meta.json`).
- **Motion-aware**: `walk` и `active` определяются по смещению центра стабильных точек (nose, withers, mid_spine, hip). `active` требует 3 условия одновременно — delta, delta/frame_gap, bbox_moved_ratio — чтобы не путать с обычным покачиванием камеры.
- **Ручная установка** — кнопки в панели или горячие клавиши 1..6.
- **Валидация экспертом**: в панели атрибутов кнопка «✅ валидация» — эксперт вводит истинное поведение, приложение сравнивает с авто-разметкой и показывает совпадение.

### 🎯 Трекинг и ReID
- **ByteTrack** — автоматическое присвоение `animal_id` по видео.
- **ReID (восстановление ID)** — если животное перекрыто, ID восстанавливается по эмбеддингу. Поддерживается кросс-камерный ReID через глобальный пул потерянных треков.
- **Панель треков** — слияние, переназначение, удаление, метрики разрывов (single-frame tracks, gaps > 3 кадров).
- **Вектор движения** — визуализация перемещения bbox между кадрами.
- **Экспорт треков** в JSON и CSV.
- **Метрики качества трекинга**: MOTA / IDF1 (кнопка в панели управления треками).

### 🧪 MLOps и Data Versioning
- **Экспорт в ONNX** (кнопка у модели): `opset=12`, `simplify`, `dynamic`. Сохраняется в `models/`.
- **Версии датасета**: снимки (hash) в модалке `📋 Версии`.
- **Diff версий**: выбор двух версий чекбоксами и наглядное сравнение — добавлено/удалено фото, рамок, скелетов и поведений.
- **Active Learning**: фильтр «Неуверенные» в сайдбаре — запрашивает у YOLO очередь кадров, где уверенность модели в диапазоне `[0.3, 0.6]`.
- **ML-классификатор поведения**: обучение через кнопку в настройках проекта. При смене класса проекта (если обучен на другой) — показывается предупреждение.
- **Headless CLI**: `python cli.py run-pipeline --input video.mp4 --project my_proj --autolabel --export-yolo` — запуск пайплайна без веб-интерфейса.

### 🔍 Валидатор разметки и Качество датасета
- **Кнопка «📊 Качество датасета»** в сайдбаре — открывает модалку с агрегированными карточками по всем проверкам.
- **9 типов проверок** (сервер `/api/projects/{id}/validate`):
  - `small_box` — площадь рамки < 0.5% от кадра;
  - `overlap` — IoU двух рамок > 0.9;
  - `out_of_bounds` — рамка выходит за границы кадра;
  - `nested_box` — одна рамка вложена в другую > 90%;
  - `aspect` — соотношение сторон > 5:1;
  - `single_frame_track` — трек длиной в 1 кадр (подозрительно);
  - `behavior_jitter` — поведение меняется чаще, чем в 50% кадров трека;
  - `blurry` — размытые кадры (Laplacian variance < 100, deep-режим);
  - `occluded_keypoint` — точки скелета с visibility < 0.5.
- **Кликабельные карточки-фильтры** — нажатие на «Маленькие» показывает только такие проблемы.
- **Клик по проблеме** — открывает соответствующий кадр в редакторе.
- **Deep-режим** (`?deep=true`) — включает blur-проверку через OpenCV (медленнее, для финальной приёмки датасета).

### 🔒 Безопасность и приватность
- **Auto-Blur**: автоматическое размытие фона (люди, машины, номера) на новых фото в фоне. Настраивается per-project, выбираются классы.
- **CSRF (double-submit)**: cookie `pdb_csrf` + заголовок `X-CSRF-Token`. Заголовок `X-Requested-With` остаётся как второй слой защиты. Отключается через `CSRF_STRICT=0` для тестов.
- **CSP**: `default-src 'self'`, `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- **Zip-slip / path traversal**: безопасная распаковка (проверка абсолютных путей, NUL-байтов, симлинков, ratio компрессии).
- **SSRF-защита**: все внешние URL (import URL, Roboflow, Supervisely, Labelbox, Scale AI, V7 Darwin, Webhooks) проходят через `is_safe_external_url()` — блокируются localhost, приватные сети и metadata-IP (169.254.169.254).
- **ffmpeg allowlist**: через `/api/system/ffmpeg/set_path` можно указать только настоящий `ffmpeg`/`ffmpeg.exe` — проверяется `-version` и наличие строки `ffmpeg version` в выводе. Произвольный исполняемый файл не запустится.
- **Rate limiting** на тяжелые операции (upload, import, autolabel, train, login).
- **argon2** для паролей (без fallback на SHA256 в проде).
- **Constant-time сравнение** Bearer-токена в API v2 и CSRF-токенов.
- **Аудит**: Запись всех POST/PUT/DELETE действий пользователей в БД (кто удалил, кто обучил, статус, длительность). Просмотр в «История статусов» с фильтром по пользователю.
- **RBAC**: Проверка прав на уровне API (если пользователь вызывает запрещенный эндпоинт, сервер возвращает 403) + скрытие UI-кнопок через `data-requires`.

### 🎥 Видео
- **Извлечение кадров** через ffmpeg (mp4 / mov / avi / mkv / webm).
- **Кастомный плеер**: перемотка по кадрам, скорость, Seek-бар.
- **Точная отрисовка рамок**: исправлен баг с letterbox (рамки больше не растягиваются).
- **Переключатель** «Показывать рамки» в плеере.
- **Интерполяция bbox и keypoints** между двумя ключевыми кадрами для плавности.

### 🤖 Обучение
- **Два режима**: детектор (bbox) и **pose** (скелет).
- **Fine-tune YOLOv8 / YOLO11 / YOLO26** (nano / small / medium / large / xlarge) из UI.
- **Live-прогресс** через SSE + графики mAP/loss в реальном времени.
- **Сравнение моделей** side-by-side (два прогона в одном окне).
- **Автоактивация** новой модели и сохранение `last.pt` при остановке (можно продолжить с чекпоинта).
- **Автоподбор** предобучения (OpenImages V7 / COCO) — OIV7 недоступен для YOLO11-detect и Pose, интерфейс это учитывает.

### 🎨 Организация и Интерфейс
- **Мультиклассовые проекты**, **Теги** (CRUD + чипсы под холстом), **Корзина** (с настраиваемым TTL, восстановление).
- **Виртуальный скролл** (списки по 100k+ фото без тормозов), **Drag-n-drop** между проектами.
- **Apple HIG-inspired** дизайн — Liquid Glass, spring-анимации, haptics.
- **Тёмная / светлая / авто** тема, **Русский / English** интерфейс.
- **Command palette** (⌘K), **Focus-режим** (⌘\), **Горячие клавиши**.
- **Onboarding Tour**: интерактивный тур по ключевым элементам интерфейса при первом запуске (7 шагов). Кнопка «?» в шапке — повторный запуск.
- **Руководство пользователя** (Guide): пошаговая инструкция из 17 шагов (от создания проекта до работы с версиями, Webhooks, ONNX, валидатором).
- **История изменений** (Changelog): кликабельная версия в шапке — модалка со списком всех версий и изменений.
- **Управление треками**: панель с merge / reassign / delete + метрики MOTA/IDF1.
- **Мобильная адаптивность**: сайдбар сворачивается, тач-таргеты увеличены, pinch-to-zoom и pan двумя пальцами.
- **Developer Mode**: чекбокс в настройках открывает панель с текущим состоянием разметки и кнопкой «скопировать cURL» для отладки API.

---

## 🚀 Быстрый старт

### Требования
- **Python 3.13+**
- **SQLite** *(по умолчанию)*, **MySQL 8.0+** или **PostgreSQL 14+** *(для командного режима)*
- **FFmpeg** *(опционально — для видео)*
- **scikit-learn** *(опционально — для ML-классификатора поведения)*
- **Docker + docker-compose** *(опционально — для деплоя без Python на хосте)*
- ОС: Windows 10+ / macOS 11+ / Linux

### Вариант 1: SQLite (Локальный режим)
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
Открой **http://localhost:8000** — БД создастся сама. Вход не потребуется (Local Mode).

С авто-перезагрузкой при правке `.py`:
```bash
DEBUG=1 python run.py
```

### Вариант 2: Командный режим (PostgreSQL / MySQL)
1. Поднимите сервер PostgreSQL или MySQL.
2. Создайте базу данных:
```sql
CREATE DATABASE pig_dataset CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```
3. Создай `.env` в корне проекта:
```env
DB_ENGINE=postgres
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=pig_dataset
AUTH_MODE=team
```
4. Запустите `python run.py`. Откройте браузер — вас встретит **Экран первичной настройки** для создания Администратора.

### Вариант 3: Desktop (.exe / .app / .AppImage)
```bash
pip install pyinstaller
pyinstaller build.spec
# → dist/DatasetBuilder/
```
*(Desktop-сборка работает только в локальном режиме SQLite).*

### Вариант 4: Docker (Production-like)
```bash
git clone https://github.com/Xulkvan/DatasetBuilder.git
cd DatasetBuilder

# Создай .env (можно скопировать .env.example)
cp .env.example .env
# Опционально: впиши API_KEY, пароль для БД и настрой лимиты

# Локальный режим (SQLite)
docker-compose up -d --build

# Командный режим (PostgreSQL)
docker-compose --profile team up -d --build
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
- Работает от непривилегированного пользователя (`app`)
- Healthcheck на `/api/version` (curl каждые 30 с)
- По умолчанию SQLite (`DB_ENGINE=sqlite`)

### Установка Python SDK (для B2B)
```bash
pip install ./sdk
```

### Headless CLI (без веб-интерфейса)
```bash
# Импорт видео → авторазметка → экспорт YOLO за одну команду
python cli.py run-pipeline \
    --input ./video.mp4 \
    --project my_proj \
    --create-project \
    --autolabel \
    --export-yolo
```
Полезно для CI/CD пайплайнов и серверных воркеров без GUI.

### Восстановление доступа (если пароль забыт)
```bash
# Создать/сбросить админа (только для team mode)
python -m reset_admin admin MyNewPassword123

# Или список пользователей
python -m reset_admin --list
```

---

## ⚙️ Настройка

Все параметры через `.env` (см. `.env.example` как шаблон):

```env
# БД
DB_ENGINE=sqlite | mysql | postgres
DB_PATH=data/dataset.db                                # SQLite
DB_USER / DB_PASSWORD / DB_HOST / DB_PORT / DB_NAME    # MySQL / PostgreSQL

# Командный режим (Team Edition)
AUTH_MODE=auto       # auto | local | team (auto = local для SQLite, team для PostgreSQL/MySQL)
SESSION_TTL_DAYS=7   # Время жизни сессии (в днях)
SESSION_COOKIE_SECURE=auto # auto — Secure только по HTTPS
LOCK_TTL_SECONDS=300 # Время блокировки кадра (5 минут)

# Данные
DATA_ROOT=/custom/path

# Сервер
HOST=127.0.0.1
PORT=8000
DEBUG=0

# API v2 (Bearer auth)
API_KEY=your_secret_token_here

# Безопасность
CSRF_STRICT=1                  # 1 = double-submit cookie (по умолчанию); 0 = только X-Requested-With (для тестов)
WEBHOOK_ALLOW_PRIVATE=0        # 1 = разрешить вебхуки на приватные IP (для тестов)

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
├── security.py         # CSRF + CSP middleware + Audit
├── config.py           # Единый источник констант
├── database.py         # Настройка SQLAlchemy (SQLite/MySQL/PostgreSQL)
├── models.py           # ORM-модели (Project, User, Session, ImageLock и др.)
├── schemas.py          # Pydantic-схемы
├── logger.py           # Кастомный логгер статусов
├── version.py          # Версия и тип лицензии
├── build.spec          # PyInstaller spec
├── eval_tracker.py     # Метрики MOTA / IDF1 (CLI-утилита + endpoint)
├── reset_admin.py      # Восстановление доступа (создание/сброс админа)
├── setup_tests.py      # Генератор тестов (backup, bulk_transfer)
├── run_coverage.py     # Утилита отчёта покрытия (coverage.py + htmlcov)
├── index.html          # UI
├── style.css           # стили
├── i18n.js             # словари ru/en
├── requirements.txt
├── requirements.lock   # зафиксированные версии для Docker
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── .editorconfig
├── .github/workflows/tests.yml  # CI: ruff + pytest + coverage
├── pytest.ini          # конфиг pytest (маркеры slow/ml, testpaths)
├── tsconfig.json       # JS-типизация (// @ts-check)
├── package.json
├── LICENSE
├── README.md
│
├── routers/            # Эндпоинты API
│   ├── auth.py         # Логин, логаут, смена пароля (Team Edition)
│   ├── setup.py        # Создание первого администратора
│   ├── assignments.py  # Назначение задач и ревью (Approve/Reject)
│   ├── locks.py        # Блокировка кадров (Soft Locks)
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
│   ├── auth_service.py       # Работа с сессиями (argon2, resolve_session)
│   ├── route_permissions.py  # Матрица прав (RBAC)
│   ├── auto_blur_service.py  # фоновый Auto-blur (люди/номера)
│   ├── behavior_service.py   # эвристики + ML-классификатор
│   ├── bootstrap_service.py  # загрузка стартовых моделей
│   ├── cvat_service.py       # CVAT XML import/export
│   ├── dataset_card_service.py # README.md для датасета
│   ├── ffmpeg_service.py     # работа с видео и ffmpeg
│   ├── file_service.py       # безопасность имен, magic bytes
│   ├── image_service.py      # pHash, IoU, миниатюры, кэши
│   ├── ml_service.py         # YOLO-кэш, batch-инференс
│   ├── model_cache.py        # Общий ModelCache (YOLO + SAM)
│   ├── model_provider.py     # Provider Pattern (ABC для Detector/Pose/Tracker)
│   ├── motion_service.py     # Векторы движения (вынесено из app.py)
│   ├── pipeline_service.py   # 🚀 серверный воркер
│   ├── project_service.py    # purge_projects
│   ├── rate_limiter.py       # защита от спама
│   ├── reid_service.py       # эмбеддинги для трекинга
│   ├── sam_service.py        # SAM-модели
│   ├── settings_service.py   # настройки (TTL и т.д.)
│   ├── stream_service.py     # RTSP-воркеры (OpenCV + YOLO)
│   ├── track_service.py      # Трекинг-воркер (вынесено из app.py)
│   ├── tracker_service.py    # IoU + ReID восстановление
│   ├── train_service.py      # подготовка датасетов, ONNX-экспорт
│   ├── trash_service.py      # клинап корзины
│   ├── url_safety.py         # SSRF-защита (is_safe_external_url)
│   ├── versioning_service.py # хеширование и Diff версий
│   └── webhook_service.py    # HMAC-подпись и retry
│
├── edge_runtime/       # Пакет для NVIDIA Jetson (Edge Runtime)
│   ├── Dockerfile.edge # Контейнер для JetPack 5.x (L4T r35)
│   ├── edge_server.py  # FastAPI + ONNX Runtime + RTSP
│   └── README.md       # Инструкция по запуску на Jetson
│
├── sdk/                # Python SDK
│   ├── __init__.py
│   ├── client.py       # AsyncDatasetBuilderClient (httpx)
│   └── setup.py        # pip install ./sdk
│
├── js/                 # ES-модули фронтенда
│   ├── main.js         # точка входа, связывает всё
│   ├── api.js          # сетевой слой
│   ├── auth.js         # Логин, логаут, статус
│   ├── permissions.js  # Скрытие UI кнопок по ролям (RBAC)
│   ├── locks.js        # Обработка блокировок кадров (оверлей)
│   ├── setup_wizard.js # Модалка первого запуска
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
├── tests/              # pytest-тесты (116+, включая test_auth, test_locks)
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
| <kbd>F</kbd> | Пометить как сложный кадр ⚑ |
| <kbd>L</kbd> | Заморозить / разморозить |
| <kbd>M</kbd> | SAM-режим |
| <kbd>Z</kbd> | Зум к выделенной рамке |
| <kbd>R</kbd> | Перезапустить авторазметку |
| <kbd>⇧G</kbd> | Debug-режим YOLO (все классы) |
| <kbd>⇧K</kbd> | Режим скелета (клик — точка, ПКМ — отмена) |
| <kbd>⇧N</kbd> | Создать рамку в центре кадра |
| <kbd>1</kbd> ... <kbd>6</kbd> | Назначить поведение (eat, walk, lie, drink, stand, active) |
| <kbd>0</kbd> / <kbd>⇧0</kbd> | Присвоить / сбросить animal_id |
| <kbd>N</kbd> / <kbd>P</kbd> | Следующее / предыдущее неразмеченное |
| <kbd>Alt</kbd> + <kbd>←</kbd> / <kbd>→</kbd> | Навигация по кадрам трека (animal_id) |
| <kbd>Ctrl</kbd> + <kbd>0</kbd> | Сбросить zoom на 100% |
| <kbd>Ctrl</kbd> + <kbd>A</kbd> | Выделить все рамки |
| <kbd>Ctrl</kbd> + клик | Мультивыбор рамок |
| <kbd>+</kbd> / <kbd>−</kbd> | Приблизить / отдалить |
| <kbd>Space</kbd> + drag | Панорамирование (при любом zoom) |
| <kbd>⌘K</kbd> | Командная палитра |
| <kbd>⌘\\</kbd> | Focus-режим |
| <kbd>H</kbd> / <kbd>?</kbd> | Открыть / закрыть окно горячих клавиш |
| <kbd>Esc</kbd> | Снять выделение / закрыть модалку |

*(Полный список — в приложении по кнопке `H` или `?`)*

---

## 🧠 Как это работает

### Командный режим (Team Edition)
- **Local Mode**: Если база данных SQLite и `AUTH_MODE=auto`, система работает как одиночная утилита. Все запросы выполняются от имени скрытого `SuperAdmin` (id=0), экран логина не показывается.
- **Team Mode**: При использовании PostgreSQL/MySQL (или `AUTH_MODE=team`), включается полноценная авторизация по кукам. Сервер проверяет права на каждом эндпоинте (через `Depends(require_permission("..."))`), а фронтенд скрывает недоступные кнопки (через `data-requires`).
- **Матрица прав**: сервер отдаёт `permissions: [...]` в `/api/auth/status` — интерфейс не «прыгает» после загрузки. При добавлении новой роли или права достаточно обновить `config.ROLE_PERMISSIONS` — фронтенд подхватит автоматически.
- **Блокировки**: При открытии кадра фронтенд шлет `POST /api/images/{id}/lock`. Если кадр свободен, сервер выдает лок на 5 минут и обновляет его по heartbeat. Если занят — возвращает `{status: 'busy'}`, и UI блокирует холст.

### Полный Pipeline
Серверный оркестратор (`services/pipeline_service.py`) выполняет 4 стадии по очереди:
1. **Detect** (YOLOv8) — создает или обновляет рамки.
2. **Pose** (YOLOv8-pose) — ставит скелеты по схеме проекта.
3. **Track** (ByteTrack) — присваивает `animal_id` по видео.
4. **Behavior** — анализирует скелет и движение (эвристика или ML-классификатор).

### Поведение: Эвристика vs ML
- **Эвристика** (bbox-relative) работает из коробки и не требует обучения. Пороги привязаны к bbox объекта, а не к пропорциям кадра — 16:9 и 1:1 дают одинаковый результат.
- **ML-классификатор** обучается через кнопку в настройках проекта на скелетных признаках (углы, расстояния). Если модель уверена в предсказании более чем на 60%, её ответ имеет приоритет. Обученная модель сохраняется в `models/behavior_clf_project_{id}.pkl` и привязана к конкретному проекту (классу животного). При смене класса — предупреждение.

### Валидатор разметки
Сервер `/api/projects/{id}/validate` проходит по всем изображениям и возвращает список проблем с указанием `image_id`, `filename` и подробностей (`detail`). UI группирует по типу в кликабельные карточки-фильтры, каждая проблема кликабельна — открывает соответствующий кадр в редакторе.

Deep-режим (`?deep=true`) дополнительно декодирует каждый JPEG и считает Laplacian variance (blur detection через OpenCV). Для проектов >10k кадров это заметно медленнее — включайте только для финальной приёмки.

### Webhooks
При сохранении разметки (`annotation.saved`), завершении обучения (`training.completed`) или экспорта (`dataset.exported`) сервер формирует JSON `{event, project_id, payload}`, подписывает его HMAC-SHA256 с `secret_key` подписки и отправляет на указанный URL с заголовком `X-DatasetBuilder-Signature`. Доставка асинхронная (фоновый поток), retry до 3 раз с exponential backoff. Все внешние URL проходят через SSRF-защиту — вебхук на `localhost` заблокируется (если не установлен `WEBHOOK_ALLOW_PRIVATE=1`).

### RTSP-стримы
При добавлении URL создается фоновый демон, который раз в секунду читает кадр (`cv2.VideoCapture`), прогоняет через YOLO, сохраняет в БД (с флагом `is_stream_frame=True`) и обновляет `animal_id` через простейший IoU-трекер + кросс-камерный ReID (глобальный пул потерянных треков). При перезапуске сервера активные стримы поднимаются автоматически. Лимит — 2 одновременных стрима на проект.

### Edge Runtime (Jetson)
Пакет, который вы скачиваете из UI, содержит `model.onnx`, скрипт `edge_server.py` и `Dockerfile`. На устройстве Jetson достаточно выполнить `docker build -t db-edge .` и запустить контейнер. Сервер сам подключится к RTSP-камере, будет прогонять кадры через ONNX Runtime и отдавать JSON по SSE (Server-Sent Events). Это позволяет развернуть инференс прямо на камере/дроне без тяжелого сервера.

### Auto-Blur
При загрузке новых фото (через UI, API, импорт или RTSP) в фоне запускается модель `yolov8n.pt`. Она ищет людей/машины (согласно настройкам проекта) и создает `BlurRegion`. При отдаче картинки через API сервер "на лету" накладывает GaussianBlur. Оригинал на диске остается чистым.

### Кастомные схемы скелета
В настройках проекта можно переопределить дефолтные 17 точек. Эта схема используется при разметке, авто-скелете, экспорте в YOLO-pose / COCO и при обучении pose-модели. Экспорт учитывает кастомную схему (`kpt_shape`, `flip_idx`).

### Active Learning (очередь неуверенных)
Фильтр «Неуверенные (Active Learning)» в меню фильтров запрашивает `/api/projects/{id}/active_learning_queue`. Сервер прогоняет активную YOLO по неразмеченным кадрам (conf=0.10) и ранжирует по `max_conf` в диапазоне `[0.3, 0.6]` — это кадры, где модель «не уверена», их разметка даст максимальный прирост качества. Инференс батчится по 8, чтобы не забивать память на больших проектах.

### Версии и Diff
Каждая версия — снимок (hash + counts). Diff двух версий показывает дельту: `+images / −images`, `+annotations / −annotations`, `+keypoints / −keypoints`, `+behaviors / −behaviors`. Удобно для отслеживания прогресса разметки и приёмки этапов.

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
