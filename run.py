"""
PigDatasetBuilder — точка входа с авто-перезагрузкой.
V6.0.0

Запуск:
    python run.py

Режимы:
    DEBUG=1 (или .env: DEBUG=1)  → uvicorn с reload, ловит правки .py
    DEBUG=0 (по умолчанию)       → uvicorn без reload, стабильный сервер

HTML/CSS/JS не триггерят перезагрузку сервера — они отдаются как файлы,
достаточно Ctrl+F5 в браузере (Cache-Control: no-cache уже стоит на них).

Переменные окружения (можно через .env):
    HOST       — по умолчанию 127.0.0.1
    PORT       — по умолчанию 8000
    DEBUG      — 1 = dev (reload), 0 = prod
    DB_USER / DB_PASSWORD / DB_HOST / DB_PORT / DB_NAME — для MySQL
"""

import os
import uvicorn

# Загружаем .env до первого обращения к os.getenv, чтобы HOST/PORT/DEBUG
# из файла подхватились в этом же процессе (app.py загрузит их ещё раз —
# это безопасно, load_dotenv не перезаписывает уже установленные переменные).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _bool_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":
    project_dir = os.path.dirname(os.path.abspath(__file__))

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    debug = _bool_env("DEBUG", "0")

    # Общие настройки для обоих режимов
    base_kwargs = dict(
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )

    if debug:
        # DEV: авто-перезагрузка при правке .py в корне проекта
        uvicorn.run(
            "app:app",                       # модуль:переменная — обязательно строка
            reload=True,
            reload_dirs=[project_dir],
            reload_excludes=[
                # Данные и артефакты — не триггерим рестарт
                "uploads/*",
                "thumbs/*",
                "models/*",
                "exports/*",
                "imports/*",
                "runs/*",
                "backups/*",
                # Окружение / зависимости
                "venv/*",
                ".venv/*",
                "node_modules/*",
                # Python-кэш
                "__pycache__/*",
                "*.pyc",
                # Конфиги и мусор
                ".env",
                ".env.*",
                ".git/*",
                "*.log",
            ],
            reload_delay=0.5,
            **base_kwargs,
        )
    else:
        # PROD: без watcher'а, стабильный сервер
        uvicorn.run(
            "app:app",
            reload=False,
            **base_kwargs,
        )