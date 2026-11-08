"""Test: smart import recognizes full DatasetBuilder backup.

Регрессия: обычный POST /api/projects/{id}/import должен распознавать
zip, созданный через /export/full, и делегировать его в
services.backup_service.import_full_project (создаёт НОВЫЙ проект),
а не прогонять через _process_dataset_zip (который ожидает COCO/YOLO/etc).

Дополнительно проверяется обратная совместимость: обычный zip с
изображением по-прежнему обрабатывается как обычно (is_full_backup
отсутствует/False).
"""
from __future__ import annotations

import io
import json
import os
import uuid
import zipfile
from datetime import datetime

from fastapi.testclient import TestClient
from PIL import Image

from app import app, SessionLocal, Project, ImageModel
from config import UPLOAD_DIR


client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def _mk_project(name: str) -> int:
    db = SessionLocal()
    try:
        p = Project(name=name, created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p)
        db.commit()
        db.refresh(p)
        return int(p.id)
    finally:
        db.close()


def _mk_image(project_id: int, filename: str = "a.jpg") -> int:
    path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}.jpg")
    Image.new("RGB", (64, 64), (100, 100, 100)).save(path, format="JPEG")
    db = SessionLocal()
    try:
        im = ImageModel(project_id=project_id, filename=filename,
                        path=path, width=640, height=640,
                        is_deleted=False,
                        file_size=os.path.getsize(path))
        db.add(im)
        db.commit()
        db.refresh(im)
        return int(im.id)
    finally:
        db.close()


# ── Smart import (полный бэкап) ─────────────────────────────────────────
def test_smart_import_recognizes_full_backup():
    pid = _mk_project(f"smart_import_src_{uuid.uuid4().hex[:6]}")
    _mk_image(pid, "smart.jpg")

    # 1) Экспорт полного бэкапа
    r = client.get(f"/api/projects/{pid}/export/full")
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type") == "application/zip"
    backup_bytes = r.content

    # 2) sanity: manifest имеет наш формат
    with zipfile.ZipFile(io.BytesIO(backup_bytes)) as z:
        assert "manifest.json" in z.namelist()
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    assert manifest.get("format") == "datasetbuilder_full_backup", manifest

    # 3) Отправляем в ОБЫЧНЫЙ /import (не /import/full)
    r = client.post(
        f"/api/projects/{pid}/import",
        files={"file": ("backup.zip", backup_bytes, "application/zip")},
    )
    assert r.status_code == 200, r.text
    data = r.json()

    # 4) Smart import распознал бэкап
    assert data.get("is_full_backup") is True, data

    # 5) Создан НОВЫЙ проект (не тот, куда "импортировали")
    new_pid = data["project_id"]
    assert new_pid != pid, "smart import должен создавать НОВЫЙ проект"

    # 6) В новом проекте есть картинки
    db = SessionLocal()
    try:
        count = db.query(ImageModel).filter(
            ImageModel.project_id == new_pid,
            ImageModel.is_deleted.is_(False),
        ).count()
        assert count >= 1, f"images in imported project: {count}"
    finally:
        db.close()


# ── Regular zip (обратная совместимость) ────────────────────────────────
def test_smart_import_regular_zip_still_works():
    pid = _mk_project(f"smart_import_regular_{uuid.uuid4().hex[:6]}")

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (50, 100, 150)).save(buf, format="JPEG")
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("regular.jpg", buf.getvalue())

    r = client.post(
        f"/api/projects/{pid}/import",
        files={"file": ("data.zip", zbuf.getvalue(), "application/zip")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # Smart-import-ответа не должно быть: это не полный бэкап
    assert not data.get("is_full_backup"), data
    # Обычный ответ _process_dataset_zip содержит format/imported_images
    assert "format" in data or "imported_images" in data, data
