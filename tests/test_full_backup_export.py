"""[BACKUP] Tests for full backup export."""
import io, json, os, zipfile
from datetime import datetime

from fastapi.testclient import TestClient

from app import (
    app, SessionLocal, Project, ImageModel, Annotation, Keypoint,
    Video, Tag, ImageTag,
)

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def _mk_project(name="fullbackup_p"):
    db = SessionLocal()
    p = Project(name=name, created_at=datetime.utcnow(), is_deleted=False,
                object_class="pig", object_class_source="list")
    db.add(p); db.commit(); db.refresh(p); pid = p.id; db.close()
    return pid


def _mk_image(pid, filename="a.jpg", phash=None):
    import uuid as _u
    from PIL import Image
    from config import UPLOAD_DIR
    path = os.path.join(UPLOAD_DIR, f"{_u.uuid4().hex}.jpg")
    Image.new("RGB", (64, 64), (100, 100, 100)).save(path, "JPEG")
    db = SessionLocal()
    im = ImageModel(project_id=pid, filename=filename, path=path,
                    width=640, height=640, is_deleted=False,
                    phash=phash, is_hard=False,
                    created_at=datetime.utcnow(),
                    file_size=os.path.getsize(path))
    db.add(im); db.commit(); db.refresh(im); iid = im.id; db.close()
    return iid


def test_export_returns_zip_with_required_files():
    pid = _mk_project()
    _mk_image(pid)

    r = client.get(f"/api/projects/{pid}/export/full")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = set(z.namelist())
    required = {"manifest.json", "project.json", "videos.json", "images.json",
                "annotations.json", "keypoints.json", "tags.json",
                "image_tags.json", "versions.json", "blur_regions.json",
                "behavior_validations.json", "streams.json", "webhooks.json"}
    assert required.issubset(names), f"missing: {required - names}"


def test_manifest_counts_match_arrays():
    pid = _mk_project()
    iid = _mk_image(pid)
    db = SessionLocal()
    a = Annotation(image_id=iid, x=0.1, y=0.1, w=0.2, h=0.2, label="pig")
    db.add(a); db.commit(); db.refresh(a)
    db.add(Keypoint(annotation_id=a.id, name="nose",
                    x=0.15, y=0.15, visibility=1.0))
    db.commit(); db.close()

    r = client.get(f"/api/projects/{pid}/export/full")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        manifest = json.loads(z.read("manifest.json"))
        images = json.loads(z.read("images.json"))
        anns = json.loads(z.read("annotations.json"))
        kps = json.loads(z.read("keypoints.json"))

    assert manifest["counts"]["images"] == len(images) == 1
    assert manifest["counts"]["annotations"] == len(anns) == 1
    assert manifest["counts"]["keypoints"] == len(kps) == 1


def test_image_files_are_included():
    pid = _mk_project()
    iid = _mk_image(pid, "myimage.jpg")

    r = client.get(f"/api/projects/{pid}/export/full")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        images = json.loads(z.read("images.json"))
        entry = images[0]
        assert entry["old_id"] == iid
        assert entry["file_ext"] == ".jpg"
        assert f"files/images/{iid}.jpg" in z.namelist()
        assert len(z.read(f"files/images/{iid}.jpg")) > 100


def test_preserves_annotation_attributes():
    pid = _mk_project()
    iid = _mk_image(pid)
    db = SessionLocal()
    a = Annotation(image_id=iid, x=0.1, y=0.2, w=0.3, h=0.4,
                   label="pig", confidence=0.87, is_frozen=True,
                   behavior="eat", behavior_source="manual", animal_id=42)
    db.add(a); db.commit(); db.close()

    r = client.get(f"/api/projects/{pid}/export/full")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        anns = json.loads(z.read("annotations.json"))
    a = anns[0]
    assert a["confidence"] == 0.87
    assert a["is_frozen"] is True
    assert a["behavior"] == "eat"
    assert a["behavior_source"] == "manual"
    assert a["animal_id"] == 42


def test_export_missing_project_returns_404():
    r = client.get("/api/projects/999999/export/full")
    assert r.status_code == 404


def test_export_empty_project():
    pid = _mk_project()
    r = client.get(f"/api/projects/{pid}/export/full")
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        manifest = json.loads(z.read("manifest.json"))
    assert manifest["counts"]["images"] == 0
    assert manifest["counts"]["annotations"] == 0


def test_export_with_video():
    from config import VIDEO_DIR
    import uuid as _u
    pid = _mk_project()
    vpath = os.path.join(VIDEO_DIR, f"{_u.uuid4().hex}.mp4")
    with open(vpath, "wb") as f:
        f.write(b"\x00\x00\x00\x1cftypmp42" + b"x" * 2000)
    db = SessionLocal()
    v = Video(project_id=pid, filename="v.mp4", path=vpath, fps=25.0,
              extract_fps=2.0, is_deleted=False)
    db.add(v); db.commit(); db.refresh(v); vid = v.id; db.close()

    r = client.get(f"/api/projects/{pid}/export/full")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        videos = json.loads(z.read("videos.json"))
        assert videos[0]["old_id"] == vid
        assert f"files/videos/{vid}.mp4" in z.namelist()


def test_export_options_streams_false_by_default():
    pid = _mk_project()
    r = client.get(f"/api/projects/{pid}/export/full")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        manifest = json.loads(z.read("manifest.json"))
    assert manifest["options"]["include_streams"] is False
    assert manifest["options"]["include_webhooks"] is False
    assert manifest["counts"]["streams"] == 0
    assert manifest["counts"]["webhooks"] == 0


def test_export_streams_with_credentials_emits_warning():
    from app import SessionLocal, Stream
    pid = _mk_project()
    db = SessionLocal()
    try:
        db.add(Stream(project_id=pid, url="rtsp://user:pass@cam/1",
                      name="cam1", is_active=False, capture_fps=1.0))
        db.commit()
    finally:
        db.close()
    r = client.get(f"/api/projects/{pid}/export/full?include_streams=true")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        manifest = json.loads(z.read("manifest.json"))
    assert any("credentials" in w for w in manifest["warnings"])


def test_export_webhook_secret_not_in_archive():
    from app import SessionLocal, Webhook
    pid = _mk_project()
    db = SessionLocal()
    try:
        db.add(Webhook(project_id=pid, url="https://example.com/h",
                       event_type="annotation.saved",
                       secret_key="super-secret-key", active=True,
                       created_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()
    r = client.get(f"/api/projects/{pid}/export/full?include_webhooks=true")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        webhooks = json.loads(z.read("webhooks.json"))
    raw = json.dumps(webhooks)
    assert "super-secret-key" not in raw, "secret leaked into archive"
