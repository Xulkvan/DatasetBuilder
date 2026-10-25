# [STAGE1:docker] DatasetBuilder — single-stage backend image.
# Frontend — vanilla JS/HTML/CSS, дополнительная сборка не нужна.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_ENGINE=sqlite \
    DB_PATH=/app/data/dataset.db \
    DATA_ROOT=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements.lock ./
# [STAGE15:docker-lock]
RUN pip install -r requirements.lock

COPY . .

RUN mkdir -p data uploads thumbs models exports runs videos imports backups js

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/version || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
