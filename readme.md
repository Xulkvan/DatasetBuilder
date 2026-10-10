\# 🐷 PigDatasetBuilder



Инструмент для разметки датасетов с автоматической детекцией свиней на базе YOLOv8.



!\[Version](https://img.shields.io/badge/version-5.4.4-blue)

!\[Python](https://img.shields.io/badge/python-3.10%2B-blue)

!\[FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)



\## Возможности



\- \*\*Авторазметка\*\* через YOLOv8 (OpenImages V7 с классом Pig / COCO)

\- \*\*Обучение модели\*\* прямо из UI — fine-tune на своём датасете

\- \*\*4 формата импорта\*\*: COCO / YOLO / CVAT XML / Label Studio

\- \*\*Экспорт\*\* в YOLO и COCO с Train/Val/Test split

\- \*\*pHash-дедупликация\*\* загружаемых изображений

\- \*\*Корзина\*\* с мягким удалением и автоочисткой

\- \*\*Теги\*\* для организации изображений

\- \*\*Валидатор разметки\*\*: мелкие рамки, вложенные, вне холста

\- \*\*Бэкап проекта\*\* в zip целиком

\- \*\*История статусов\*\* — встроенный лог событий

\- \*\*Тёмная / светлая тема\*\*, Responsive UI, поддержка тача



\## Установка



\### Требования



\- Python 3.10+

\- MySQL 8.0+



\### 1. Клонировать репозиторий



```bash

git clone https://github.com/ТВОЙ\_ЮЗЕР/pig\_dataset\_builder.git

cd pig\_dataset\_builder

