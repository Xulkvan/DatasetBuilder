"""[STAGE-SEC1] IDOR и project-access regression tests."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def team_ctx(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "idor.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    client = TestClient(app_mod.app)
    client.post("/api/setup/admin",
                json={"username": "admin", "password": "admin12345678"})
    r = client.post("/api/users", json={
        "username": "ann", "password": "ann12345678", "role": "annotator"})
    assert r.status_code == 200, r.text
    ann_id = r.json()["id"]
    r1 = client.post("/api/projects", data={"name": "P1", "object_class": "pig"})
    r2 = client.post("/api/projects", data={"name": "P2", "object_class": "pig"})
    assert r1.status_code == 200 and r2.status_code == 200
    p1, p2 = r1.json()["id"], r2.json()["id"]
    return client, ann_id, p1, p2


def test_annotator_cannot_read_foreign_project(team_ctx):
    client, ann_id, p1, p2 = team_ctx
    client.post("/api/auth/logout")
    client.post("/api/auth/login",
                json={"username": "ann", "password": "ann12345678"})
    r = client.get(f"/api/projects/{p1}/info")
    assert r.status_code == 403, r.text
    r = client.get(f"/api/projects/{p1}/stats")
    assert r.status_code == 403, r.text
    r = client.get(f"/api/projects/{p1}/versions")
    assert r.status_code == 403, r.text


def test_annotator_cannot_read_foreign_image(team_ctx):
    from app import SessionLocal
    from models import ImageModel
    client, ann_id, p1, p2 = team_ctx
    db = SessionLocal()
    try:
        im = ImageModel(project_id=p1, filename="x.jpg",
                        path="/tmp/_x.jpg", width=640, height=640,
                        is_deleted=False)
        db.add(im); db.commit(); db.refresh(im)
        img_id = im.id
    finally:
        db.close()
    client.post("/api/auth/logout")
    client.post("/api/auth/login",
                json={"username": "ann", "password": "ann12345678"})
    assert client.get(f"/api/images/{img_id}/file").status_code == 403
    assert client.get(f"/api/images/{img_id}/thumb").status_code == 403
    assert client.get(f"/api/images/{img_id}/annotations").status_code == 403


def test_manager_sees_all(team_ctx):
    client, ann_id, p1, p2 = team_ctx
    r = client.get(f"/api/projects/{p1}/info")
    assert r.status_code == 200
    r = client.get("/api/projects")
    assert len(r.json()) >= 2


def test_local_mode_no_restrictions(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "local.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    client = TestClient(app_mod.app)
    r = client.post("/api/projects", data={"name": "L1", "object_class": "pig"})
    pid = r.json()["id"]
    assert client.get(f"/api/projects/{pid}/info").status_code == 200


def test_import_local_folder_blocked_for_foreign_project(team_ctx, tmp_path):
    """[STAGE2] Annotator не может импортировать из локальной папки
    в чужой проект (интеграция project_access + import_local_folder)."""
    import os as _os
    from PIL import Image as _Image
    from config import IMPORT_DIR as _IMPORT_DIR

    client, ann_id, p1, p2 = team_ctx
    test_dir = _os.path.join(_IMPORT_DIR, "test_import_folder_stage2")
    _os.makedirs(test_dir, exist_ok=True)
    _Image.new("RGB", (32, 32), (100, 100, 100)).save(
        _os.path.join(test_dir, "a.jpg"))

    client.post("/api/auth/logout")
    client.post("/api/auth/login",
                json={"username": "ann", "password": "ann12345678"})
    r = client.post(f"/api/projects/{p1}/import/local_folder",
                    json={"path": test_dir, "recursive": False})
    assert r.status_code == 403, r.text

    # cleanup
    try:
        _os.remove(_os.path.join(test_dir, "a.jpg"))
        _os.rmdir(test_dir)
    except OSError:
        pass
