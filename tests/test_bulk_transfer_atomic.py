"""[STAGE7] Regression: _bulk_transfer должен быть атомарным.

До STAGE7 при ошибке на середине копирования (например, второй
shutil.copyfile падал) в БД уже успевали закоммититься новые
ImageModel, а файлы оставались на диске. Теперь:
  * при любом исключении — db.rollback() + удаление _created_paths;
  * endpoint возвращает 500, в целевом проекте 0 новых изображений.

ВАЖНО: TestClient создаётся с raise_server_exceptions=False.
Starlette ServerErrorMiddleware пробрасывает unhandled exception
даже после отправки 500-ответа (для логирования на ASGI-уровне),
а TestClient по умолчанию ре-раизит это исключение в тесте. Без
этого флага r.status_code никогда не прочитается.
"""

import importlib
import os
import shutil as _shutil
import uuid as _uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def local_ctx(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "s7.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("CSRF_STRICT", "0")
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    client = TestClient(
        app_mod.app,
        headers={"X-Requested-With": "DatasetBuilder"},
        raise_server_exceptions=False,
    )
    return client, app_mod


def _mk_image_file(upload_dir):
    from pathlib import Path
    p = Path(upload_dir) / (f"t7_{_uuid.uuid4().hex[:8]}.jpg")
    Image.new("RGB", (64, 64), (100, 100, 100)).save(p, format="JPEG")
    return str(p)


def _mk_project(db, name):
    from datetime import datetime
    from models import Project
    p = Project(name=name, created_at=datetime.utcnow(),
                is_deleted=False, object_class="pig",
                object_class_source="list")
    db.add(p); db.commit(); db.refresh(p)
    return p.id


def _mk_image(db, pid, path, fname):
    from datetime import datetime
    from models import ImageModel
    im = ImageModel(project_id=pid, filename=fname, path=path,
                    width=640, height=640, is_deleted=False,
                    created_at=datetime.utcnow(),
                    file_size=100)
    db.add(im); db.commit(); db.refresh(im)
    return im.id


def test_bulk_transfer_atomic(local_ctx, monkeypatch, tmp_path):
    """POST /api/images/bulk_copy_to_project -> 500 при сбое, 0 новых images."""
    client, app_mod = local_ctx
    from config import UPLOAD_DIR

    db = app_mod.SessionLocal()
    try:
        src_pid = _mk_project(db, "s7_atomic_src")
        dst_pid = _mk_project(db, "s7_atomic_dst")
        p1 = _mk_image_file(UPLOAD_DIR)
        p2 = _mk_image_file(UPLOAD_DIR)
        i1 = _mk_image(db, src_pid, p1, "a.jpg")
        i2 = _mk_image(db, src_pid, p2, "b.jpg")
    finally:
        db.close()

    real_copyfile = _shutil.copyfile
    calls = {"n": 0}

    def _flaky(src, dst, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_copyfile(src, dst, *a, **kw)
        raise RuntimeError("boom on second copy")

    monkeypatch.setattr(_shutil, "copyfile", _flaky)

    before_files = set(os.listdir(UPLOAD_DIR))
    allowed_files = before_files | {
        os.path.basename(p1), os.path.basename(p2),
    }

    r = client.post("/api/images/bulk_copy_to_project", json={
        "image_ids": [i1, i2], "target_project_id": dst_pid,
    })
    assert r.status_code == 500, (
        f"expected 500 after internal error, got {r.status_code}: {r.text[:300]}"
    )

    db = app_mod.SessionLocal()
    try:
        from models import ImageModel
        n = (db.query(ImageModel)
               .filter(ImageModel.project_id == dst_pid,
                       ImageModel.is_deleted.is_(False))
               .count())
        assert n == 0, f"partial commit: {n} images in dst"
    finally:
        db.close()

    after_files = set(os.listdir(UPLOAD_DIR))
    extra = after_files - allowed_files
    assert not extra, f"leftover files after rollback: {sorted(extra)}"
