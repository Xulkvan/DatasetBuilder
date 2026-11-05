"""[FIX:STAGE2-backup] Изолированные тесты backup_project.

Каждый тест:
  * использует свой tmp_path (через local_client);
  * использует свой app (importlib.reload после monkeypatch.setenv);
  * config.BACKUP_DIR и app.BACKUP_DIR видят один и тот же путь.

Это исправляет старую проблему, когда test_auth.py глобально
перезагружал config с DATA_ROOT=test_argon2_hash_accepted0\backups,
и test_backup.py (без изоляции) писал backup в одну папку,
а download искал в другой.
"""
import importlib
import io
import json
import zipfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def local_client(monkeypatch, tmp_path, clean_auth_db):
    """Свой app с изолированным DATA_ROOT / BACKUP_DIR / DB."""
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "backup.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("CSRF_STRICT", "0")
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    c = TestClient(app_mod.app, headers={"X-Requested-With": "DatasetBuilder"})
    # Возвращаем и модуль для доступа к SessionLocal / моделям
    return c, app_mod


def _mk_project(db, name):
    from models import Project
    p = Project(name=name, created_at=datetime.utcnow(),
                is_deleted=False, object_class="pig",
                object_class_source="list")
    db.add(p); db.commit(); db.refresh(p)
    return p.id


def _mk_image(db, project_id, filename="a.jpg"):
    from models import ImageModel
    im = ImageModel(
        project_id=project_id, filename=filename,
        path="/tmp/_nonexistent_" + filename,
        width=640, height=640, is_deleted=False,
    )
    db.add(im); db.commit(); db.refresh(im)
    return im.id


def _mk_annotation(db, image_id, **kw):
    from models import Annotation
    a = Annotation(
        image_id=image_id,
        x=kw.get("x", 0.1), y=kw.get("y", 0.1),
        w=kw.get("w", 0.2), h=kw.get("h", 0.2),
        label=kw.get("label", "pig"),
        confidence=kw.get("confidence"),
        is_frozen=kw.get("frozen", False),
        behavior=kw.get("behavior"),
        animal_id=kw.get("animal_id"),
    )
    db.add(a); db.commit(); db.refresh(a)
    return a.id


def _mk_keypoint(db, annotation_id, name, x, y, vis=1.0):
    from models import Keypoint
    kp = Keypoint(annotation_id=annotation_id, name=name,
                  x=x, y=y, visibility=vis)
    db.add(kp); db.commit(); db.refresh(kp)
    return kp.id


def _backup_and_download(client, pid):
    """POST /backup -> GET /backup/download/{filename}. Возвращает (body, anns)."""
    r = client.post(f"/api/projects/{pid}/backup")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    filename = body["filename"]

    r2 = client.get(f"/api/projects/{pid}/backup/download/{filename}")
    assert r2.status_code == 200, (
        f"download failed: {r2.status_code} {r2.text[:300]}")
    with zipfile.ZipFile(io.BytesIO(r2.content)) as z:
        names = z.namelist()
        assert "annotations.json" in names
        assert "meta.json" in names
        raw = z.read("annotations.json").decode("utf-8")
        return body, json.loads(raw)


class TestBackupPreservesAttributes:
    def test_behavior_and_animal_id_in_backup(self, local_client):
        client, app_mod = local_client
        db = app_mod.SessionLocal()
        try:
            pid = _mk_project(db, "backupAttrs")
            iid = _mk_image(db, pid, "a.jpg")
            _mk_annotation(db, iid, x=0.1, y=0.1,
                           behavior="eat", animal_id=42)
            _mk_annotation(db, iid, x=0.5, y=0.5,
                           behavior="stand", animal_id=7)
        finally:
            db.close()

        _body, anns = _backup_and_download(client, pid)
        bucket = anns[str(iid)]
        assert len(bucket) == 2
        by_aid = {a["animal_id"]: a for a in bucket}
        assert set(by_aid.keys()) == {42, 7}
        assert by_aid[42]["behavior"] == "eat"
        assert by_aid[7]["behavior"] == "stand"

    def test_keypoints_in_backup(self, local_client):
        client, app_mod = local_client
        db = app_mod.SessionLocal()
        try:
            pid = _mk_project(db, "backupKP")
            iid = _mk_image(db, pid, "b.jpg")
            aid = _mk_annotation(db, iid, x=0.2, y=0.2)
            _mk_keypoint(db, aid, "nose", 0.25, 0.25, vis=1.0)
            _mk_keypoint(db, aid, "withers", 0.30, 0.28, vis=0.7)
        finally:
            db.close()

        _body, anns = _backup_and_download(client, pid)
        bucket = anns[str(iid)]
        assert len(bucket) == 1
        kps = bucket[0]["keypoints"]
        assert len(kps) == 2
        by_name = {k["name"]: k for k in kps}
        assert by_name["nose"]["x"] == 0.25
        assert by_name["nose"]["visibility"] == 1.0
        assert by_name["withers"]["visibility"] == 0.7

    def test_annotation_without_attrs_has_empty_defaults(self, local_client):
        client, app_mod = local_client
        db = app_mod.SessionLocal()
        try:
            pid = _mk_project(db, "backupEmpty")
            iid = _mk_image(db, pid, "c.jpg")
            _mk_annotation(db, iid, x=0.1, y=0.1)
        finally:
            db.close()

        _body, anns = _backup_and_download(client, pid)
        a = anns[str(iid)][0]
        assert a["behavior"] is None
        assert a["animal_id"] is None
        assert a["keypoints"] == []

    def test_multiple_images_not_mixed(self, local_client):
        client, app_mod = local_client
        db = app_mod.SessionLocal()
        try:
            pid = _mk_project(db, "backupMulti")
            i1 = _mk_image(db, pid, "x1.jpg")
            i2 = _mk_image(db, pid, "x2.jpg")
            a1 = _mk_annotation(db, i1, x=0.1, y=0.1, animal_id=1)
            a2 = _mk_annotation(db, i2, x=0.2, y=0.2, animal_id=2)
            _mk_keypoint(db, a1, "nose", 0.11, 0.11)
            _mk_keypoint(db, a2, "nose", 0.21, 0.21)
            _mk_keypoint(db, a2, "tail_base", 0.25, 0.25)
        finally:
            db.close()

        _body, anns = _backup_and_download(client, pid)
        assert len(anns[str(i1)]) == 1
        assert len(anns[str(i2)]) == 1
        assert len(anns[str(i1)][0]["keypoints"]) == 1
        assert len(anns[str(i2)][0]["keypoints"]) == 2

    def test_backup_counts_match(self, local_client):
        client, app_mod = local_client
        db = app_mod.SessionLocal()
        try:
            pid = _mk_project(db, "backupCounts")
            iid = _mk_image(db, pid, "d.jpg")
            _mk_annotation(db, iid)
            _mk_annotation(db, iid)
            _mk_annotation(db, iid)
        finally:
            db.close()

        body, _anns = _backup_and_download(client, pid)
        assert body["images_count"] == 1
        assert body["annotations_count"] == 3
