<div align="center">

# 🐷 PigDatasetBuilder

**Инструмент для разметки датасетов с авторазметкой на YOLOv8**

От загрузки фото до обученной модели — всё в одном веб-интерфейсе.

[![Version](https://img.shields.io/badge/version-5.5.0-0071e3?style=flat-square)](https://github.com/Xulkvan/PigDatasetBuilder)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?style=flat-square&logo=mysql&logoColor=white)](https://www.mysql.com/)
[![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-FF6B35?style=flat-square)](https://github.com/ultralytics/ultralytics)
[![License](https://img.shields.io/badge/license-MIT-34c759?style=flat-square)](LICENSE)

</div>

---

## ✨ Что это

**PigDatasetBuilder** — веб-приложение для быстрой разметки датасетов свиней с полным циклом:

1. **Загрузка** фото или импорт готового датасета (COCO / YOLO / CVAT / Label Studio)
2. **Авторазметка** нейросетью — YOLOv8 рисует рамки сам, ты только правишь
3. **Обучение** — когда накопилось 50+ размеченных кадров, обучаешь свою модель прямо из UI
4. **Экспорт** — YOLO или COCO с автоматическим train/val/test split

Всё работает **локально**: данные остаются на твоём компьютере, никаких облаков.

---

## 🎬 Возможности

### 🖼 Разметка
- **Авторазметка** через YOLOv8 (OpenImages V7 с классом Pig / COCO)
- **Ручное рисование** рамок мышью или пальцем (планшет)
- **Мультивыбор** рамок (`Shift+клик`), групповое перемещение и удаление
- **Заморозка** рамок — защита от перезаписи при повторной авторазметке
- **Undo/Redo** — Ctrl+Z / Ctrl+Y на 50 шагов назад
- **Zoom/Pan** холста — колесо мыши, pinch-zoom на тач-устройствах

### 📦 Импорт / Экспорт
- **Импорт целиком**: zip с картинками + разметкой (автодетект формата)
- **4 формата**: COCO JSON, YOLO TXT, CVAT XML, Label Studio JSON
- **pHash-дедупликация** — одинаковые фото отсеиваются автоматически
- **Экспорт** в YOLO / COCO с разбиением на train / val / test (70/20/10, 80/20, 85/10/5)

### 🤖 Обучение
- **Fine-tune** любой YOLOv8 модели (nano / small / medium) прямо из UI
- **Live-прогресс** через Server-Sent Events — видно каждую эпоху и loss
- **Автоактивация** новой модели после обучения
- **Выбор предобучения**: OpenImages V7 (601 класс, есть Pig) или COCO

### 🎨 Организация
- **Теги** — цветные метки для группировки фото
- **Корзина** — мягкое удаление с автоочисткой через N дней
- **Фильтры** — по статусу (не размеченные, с низкой уверенностью, «сложные»)
- **Поиск** по имени файла
- **Сортировка** по имени / типу / уверенности

### 🛠 Инструменты
- **Валидатор разметки** — находит мелкие, вложенные, наложение, выход за холст
- **Статистика проекта** — распределение по уверенности, топ-10 сомнительных
- **Похожие кадры** — поиск по pHash + копирование разметки
- **CSV-экспорт** статистики по всем изображениям
- **Бэкап проекта** — полная копия в zip (фото + разметка + теги)
- **История статусов** — встроенный лог событий (in-memory)

### 🎨 Интерфейс
- **Apple HIG-inspired** дизайн — Liquid Glass, spring-анимации, haptics
- **Тёмная / светлая / авто** тема
- **Тонкая настройка под тач** — крупные хендлы, увеличенные чекбоксы
- **Горячие клавиши** — от `A` (авторазметка) до `?` (шпаргалка)
- **Кастомные тултипы**, скелетоны загрузки, материализация модалок

---

## 🚀 Быстрый старт

### Требования

- **Python 3.10+**
- **MySQL 8.0+**
- ОС: Windows / macOS / Linux

### 1. Клонировать

```bash
git clone https://github.com/Xulkvan/PigDatasetBuilder.git
cd PigDatasetBuilder
```

### 2. Создать базу данных

Открой MySQL-клиент и выполни:

```sql
CREATE DATABASE pig_dataset CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 3. Виртуальное окружение

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 4. Установить зависимости

```bash
pip install -r requirements.txt
```

### 5. Запустить

```bash
python run.py
```

Открой в браузере: **http://localhost:8000**

При первом запуске автоматически скачается модель `yolov8n-oiv7.pt` (6 МБ) для авторазметки.

---

## ⚙️ Настройка

Все параметры БД можно менять через переменные окружения:

```bash
DB_USER=root DB_PASSWORD=secret DB_HOST=localhost python run.py
```

Или создай файл `.env` рядом с `app.py`:

```env
DB_USER=root
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=3306
DB_NAME=pig_dataset
```

Или через файл `.env.example` как шаблон.

---

## 🗂 Структура проекта

```
PigDatasetBuilder/
├── app.py              # FastAPI backend (все эндпоинты)
├── run.py              # точка входа с hot-reload
├── index.html          # UI разметки
├── style.css           # все стили
├── app.js              # фронтенд-логика
├── requirements.txt    # зависимости Python
├── .gitignore
│
├── models/             # .pt-модели (не в git)
├── uploads/            # фото датасета (не в git)
├── thumbs/             # превью 64×64
├── exports/            # экспорт YOLO/COCO
├── imports/            # временная папка импорта
├── runs/               # результаты обучения
└── backups/            # zip-бэкапы проектов
```

---

## ⌨️ Горячие клавиши

| Клавиша | Действие |
|:---|:---|
| <kbd>A</kbd> | Авторазметка текущего кадра |
| <kbd>R</kbd> | Перезапустить авторазметку |
| <kbd>S</kbd> / <kbd>⌘S</kbd> | Сохранить разметку |
| <kbd>Enter</kbd> | Принять и перейти к следующему неразмеченному |
| <kbd>D</kbd> / <kbd>Delete</kbd> | Удалить выделенные рамки |
| <kbd>C</kbd> | Очистить все рамки |
| <kbd>F</kbd> | Пометить как «сложный» |
| <kbd>L</kbd> | Заморозить / разморозить рамки |
| <kbd>N</kbd> / <kbd>P</kbd> | Следующее / предыдущее неразмеченное |
| <kbd>⌘Z</kbd> / <kbd>⌘Y</kbd> | Отменить / повторить |
| <kbd>H</kbd> или <kbd>?</kbd> | Все горячие клавиши |
| <kbd>Пробел</kbd> + drag | Панорамирование холста |
| Колесо мыши | Zoom к курсору |
| Pinch (2 пальца) | Zoom на тач-устройствах |

---

## 🧠 Как это работает

### Авторазметка
YOLOv8 обрабатывает кадр, оставляет только детекции класса `pig` (также `wild boar`, `boar`, `hog`, `piglet`, `swine`), дедуплицирует их по IoU > 0.5 и сохраняет в БД. Замороженные вручную рамки **не перезаписываются**.

### pHash-дедупликация
При загрузке каждого фото считается перцептивный хеш (DCT, 64 бита). Поиск дубликатов идёт **по бакетам** (первые 4 hex-символа) — это в разы быстрее, чем сравнивать со всеми фото проекта. Порог Hamming ≤ 6.

### Обучение
1. Все **размеченные** изображения проекта копируются в `runs/train_<ts>/dataset/`.
2. Автоматический split **85% train / 15% val** (детерминированно, seed=42).
3. Запускается `yolo detect train` с `freeze=8`, `lr0=0.001`, `cos_lr=True`.
4. Прогресс стримится в UI через SSE — видна каждая эпоха.
5. По завершении `best.pt` копируется в `models/` и активируется.

### Бэкап
Один zip содержит:
- `meta.json` — версия, дата, количество фото/рамок/тегов
- `images_index.json` — метаданные каждого фото
- `annotations.json` — все рамки по image_id
- `tags.json` — теги и их привязки
- `images/<id>.jpg` — сами фото

---

## 🛠 Технологии

| Слой | Стек |
|:---|:---|
| **Backend** | FastAPI, Uvicorn, SQLAlchemy 2.0, Pydantic 2 |
| **База данных** | MySQL 8 (utf8mb4) |
| **ML** | Ultralytics YOLOv8, Pillow, NumPy (через ultralytics) |
| **Frontend** | Vanilla JS (ES2020), CSS3 (backdrop-filter, CSS Grid) |
| **Real-time** | Server-Sent Events (обучение, батч-авторазметка, скачивание моделей) |
| **Хеширование** | Perceptual Hash (pHash) на базе DCT |

**Без** React / Vue / Tailwind / jQuery. Весь UI — на чистом JS + CSS.

---

## 📸 Скриншоты

> _Скриншоты добавь сам — сделай пару снимков разметки, статистики и модалки обучения._

```markdown
![Разметка](docs/screenshot-annotation.png)
![Статистика](docs/screenshot-stats.png)
![Обучение](docs/screenshot-train.png)
```

---

## ❓ FAQ

**Где хранятся фото и разметка?**
Фото — в `uploads/`, метаданные и разметка — в MySQL (`pig_dataset`). Модели — в `models/`. Всё локально, ничего не уходит в облако.

**Что делать если нет видеокарты?**
Всё работает на CPU. Обучение будет медленнее, но авторазметка и разметка — быстро.

**Как перенести проект на другой компьютер?**
Сделай бэкап (Настройки → Сделать бэкап), скопируй zip и папку `uploads/`. На новом компьютере — импорт zip через UI (кнопка «Импорт»).

**Сколько фото нужно для хорошего обучения?**
Минимум 30–50 размеченных. Для стабильного результата — 200+.

**Работает на телефоне / планшете?**
Да, с поддержкой тача (pinch-zoom, панорамирование двумя пальцами, крупные хендлы).

---

## 🤝 Contributing

Приветствуются PR и issue. Если что-то находит баг или есть идея — открывай issue на GitHub.

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
