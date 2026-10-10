"""
Точка входа с авто-перезагрузкой.

Запуск:
    python run.py

При изменении любого .py в проекте uvicorn перезапустит сервер
автоматически (задержка 0.5 сек). HTML/CSS/JS не трогают сервер —
они отдаются как файлы, достаточно Ctrl+F5 в браузере.
"""

import os
import uvicorn


if __name__ == "__main__":
    project_dir = os.path.dirname(os.path.abspath(__file__))
    uvicorn.run(
        "app:app",                    # модуль:переменная — обязательно строка
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,                  # ← авто-перезагрузка при правке .py
        reload_dirs=[project_dir],    # следим только за корнем проекта
        reload_excludes=[             # не триггерим рестарт на данные
            "uploads/*",
            "thumbs/*",
            "models/*",
            "exports/*",
            "imports/*",
            "runs/*",
            "backups/*",
            "venv/*",
            ".venv/*",
            "__pycache__/*",
            "*.pyc",
        ],
        reload_delay=0.5,
        log_level="info",
    )