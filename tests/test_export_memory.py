"""[STAGE6] export_full_project работает на большом наборе с bounded memory.

Регрессия: до STAGE6_PERF_MEMORY export_full_project делал .all() и держал
списки images/annotations/keypoints в памяти. Для проекта 50k+ изображений
это OOM. Теперь используется yield_per(1000) + _write_json_stream.

Тест создаёт 500 пустых ImageModel (без файлов на диске) — экспорт
проходит без OOM, zip создаётся, manifest.counts.images == 500.
"""
import io
import json
import zipfile
from datetime import datetime

from fastapi.testclient import TestClient

from app import app, SessionLocal, Project, ImageModel

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def test_export_500_images_streams_ok():
    db = SessionLocal()
    try:
        p = Project(
            name="stage6_export_mem",
            created_at=datetime.utcnow(),
            is_deleted=False,
            object_class="pig",
            object_class_source="list",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        pid = p.id
        for k in range(500):
            im = ImageModel(
                project_id=pid,
                filename=f"img_{k:04d}.jpg",
                path=f"/tmp/_stage6_nonexistent_{k}.jpg",
                width=640, height=640, is_deleted=False,
                created_at=datetime.utcnow(),
                file_size=0,
            )
            db.add(im)
        db.commit()
    finally:
        db.close()

    r = client.get(f"/api/projects/{pid}/export/full")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        assert "manifest.json" in names
        assert "images.json" in names
        assert "annotations.json" in names
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["counts"]["images"] == 500
        assert manifest["counts"]["annotations"] == 0
        assert manifest["counts"]["keypoints"] == 0
        images = json.loads(z.read("images.json"))
        assert len(images) == 500
