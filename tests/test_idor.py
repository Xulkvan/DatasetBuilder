"""IDOR и project-access regression tests."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


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


def _seed_foreign_objects(p1):
    from app import SessionLocal
    from models import ImageModel, Video
    db = SessionLocal()
    try:
        img = ImageModel(project_id=p1, filename="x.jpg", path="/tmp/_x.jpg",
                         width=640, height=640, is_deleted=False)
        vid = Video(project_id=p1, filename="v.mp4", path="/tmp/_v.mp4",
                    is_deleted=False)
        db.add(img); db.add(vid)
        db.commit(); db.refresh(img); db.refresh(vid)
        return img.id, vid.id
    finally:
        db.close()


@pytest.mark.parametrize("template", [
    "/api/projects/{p1}/videos",
    "/api/projects/{p1}/duplicates",
    "/api/projects/{p1}/validate",
    "/api/projects/{p1}/export/yolo",
    "/api/projects/{p1}/export/coco",
    "/api/projects/{p1}/export/agtech_csv",
])
def test_annotator_cannot_access_foreign_project_endpoints(
        ann_client, template):
    client, _ann_id, p1, _p2 = ann_client
    assert client.get(template.format(p1=p1)).status_code == 403


@pytest.mark.parametrize("method,template", [
    ("get", "/api/videos/{vid}"),
    ("delete", "/api/videos/{vid}"),
    ("get", "/api/videos/{vid}/track/status"),
    ("post", "/api/videos/{vid}/track/stop"),
    ("get", "/api/videos/{vid}/track/metrics"),
])
def test_annotator_cannot_access_foreign_video_endpoints(
        ann_client, method, template):
    client, _ann_id, p1, _p2 = ann_client
    _img_id, vid = _seed_foreign_objects(p1)
    r = getattr(client, method)(template.format(vid=vid))
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("template", [
    "/api/projects/{p1}/similar/{img}",
    "/api/images/{img}/similar_with_skeleton",
])
def test_annotator_cannot_access_foreign_image_endpoints(
        ann_client, template):
    client, _ann_id, p1, _p2 = ann_client
    img, _vid = _seed_foreign_objects(p1)
    assert client.get(template.format(p1=p1, img=img)).status_code == 403


def test_annotator_cannot_mutate_foreign_image(ann_client):
    client, _ann_id, p1, _p2 = ann_client
    img, _vid = _seed_foreign_objects(p1)
    assert client.post(f"/api/images/{img}/predict_behavior",
                       json={}).status_code == 403
    assert client.post(f"/api/images/{img}/autolabel_debug",
                       json={}).status_code == 403
    assert client.post(
        f"/api/images/{img}/copy_annotations_from/{img}").status_code == 403
    assert client.post("/api/images/bulk_rename",
                       json={"image_ids": [img]}).status_code == 403


def test_annotator_cannot_interpolate_foreign_annotations(ann_client):
    from app import SessionLocal
    from models import Video, ImageModel, Annotation

    client, _ann_id, p1, p2 = ann_client
    db = SessionLocal()
    try:
        vid = Video(project_id=p1, filename="v.mp4", path="/tmp/_v.mp4",
                    fps=25.0, extract_fps=2.0, is_deleted=False)
        db.add(vid); db.commit(); db.refresh(vid)
        frames = []
        for idx in (0, 2):
            im = ImageModel(project_id=p1, filename=f"f{idx}.jpg",
                            path=f"/tmp/_f{idx}.jpg", width=640, height=640,
                            is_deleted=False, video_id=vid.id,
                            frame_index=idx)
            db.add(im); db.commit(); db.refresh(im)
            frames.append(im.id)
        anns = []
        for iid in frames:
            a = Annotation(image_id=iid, x=0.1, y=0.1, w=0.2, h=0.2,
                           label="pig", is_frozen=False, animal_id=1)
            db.add(a); db.commit(); db.refresh(a)
            anns.append(a.id)
    finally:
        db.close()

    r = client.post(f"/api/projects/{p2}/interpolate", json={
        "animal_id": 1, "from_ann_id": anns[0], "to_ann_id": anns[1],
    })
    assert r.status_code == 403, r.text


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
