"""[BACKUP] Roundtrip tests using real fixture from stage 1."""
import io, json, os, zipfile
from pathlib import Path
import pytest as _pytest_fixture
from fastapi.testclient import TestClient

from app import (
    app, SessionLocal, Project, ImageModel, Annotation, Keypoint,
    Tag, ImageTag,
)
from models import DatasetVersion, Stream, Webhook

FIXTURE = Path(__file__).parent / "fixtures" / "sample_full_backup.zip"

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


@_pytest_fixture.fixture(autouse=True)
def _reset_import_limiter():
    try:
        from services.rate_limiter import _limiter_import
        with _limiter_import._lock:
            _limiter_import._buckets.clear()
    except Exception:
        pass
    yield




def test_fixture_exists():
    assert FIXTURE.exists(), (
        f"Missing fixture {FIXTURE}. "
        f"Create it by running export (stage 1) on a real project and "
        f"copy the zip here (≤ 1 MB)."
    )
    with zipfile.ZipFile(FIXTURE) as _zf:
        _names = set(_zf.namelist())
    _required = {"manifest.json", "project.json", "images.json",
                 "annotations.json", "keypoints.json", "videos.json"}
    _missing = _required - _names
    assert not _missing, (
        f"Fixture is not stage-1 format (missing: {sorted(_missing)}). "
        f"Regenerate via GET /api/projects/{{id}}/export/full "
        f"(or run make_backup_fixture.py for isolated generation)."
    )


def _import_fixture():
    with open(FIXTURE, "rb") as f:
        r = client.post("/api/projects/import/full",
                        files={"file": (FIXTURE.name, f, "application/zip")})
    assert r.status_code == 200, r.text
    return r.json()


def test_import_creates_project():
    data = _import_fixture()
    assert data["status"] == "ok"
    assert data["project_id"] > 0
    assert data["counts"]["images"] > 0


def test_import_restores_counts_matching_manifest():
    data = _import_fixture()
    pid = data["project_id"]

    with zipfile.ZipFile(FIXTURE) as z:
        manifest = json.loads(z.read("manifest.json"))

    db = SessionLocal()
    try:
        n_images = db.query(ImageModel).filter(
            ImageModel.project_id == pid).count()
        n_anns = (db.query(Annotation)
                    .join(ImageModel, Annotation.image_id == ImageModel.id)
                    .filter(ImageModel.project_id == pid).count())
        assert n_images == manifest["counts"]["images"]
        assert n_anns == manifest["counts"]["annotations"]
    finally:
        db.close()


def test_import_preserves_annotation_attributes():
    data = _import_fixture()
    pid = data["project_id"]

    db = SessionLocal()
    try:
        anns = (db.query(Annotation)
                  .join(ImageModel, Annotation.image_id == ImageModel.id)
                  .filter(ImageModel.project_id == pid).all())
        with zipfile.ZipFile(FIXTURE) as z:
            src_anns = json.loads(z.read("annotations.json"))
        src_aid = {a["animal_id"] for a in src_anns if a["animal_id"] is not None}
        got_aid = {a.animal_id for a in anns if a.animal_id is not None}
        assert src_aid == got_aid
    finally:
        db.close()


def test_import_files_on_disk():
    data = _import_fixture()
    pid = data["project_id"]

    db = SessionLocal()
    try:
        for im in db.query(ImageModel).filter(
                ImageModel.project_id == pid).all():
            assert os.path.exists(im.path), f"missing file: {im.path}"
    finally:
        db.close()


def test_import_invalid_zip_returns_400():
    r = client.post("/api/projects/import/full",
                    files={"file": ("bad.zip", b"not-a-zip",
                                    "application/zip")})
    assert r.status_code == 400
    db = SessionLocal()
    try:
        before = db.query(Project).count()
    finally:
        db.close()
    r2 = client.post("/api/projects/import/full",
                     files={"file": ("bad.zip", b"not-a-zip",
                                     "application/zip")})
    db = SessionLocal()
    try:
        after = db.query(Project).count()
    finally:
        db.close()
    assert before == after


def test_import_missing_manifest_returns_400():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("project.json", "{}")
    r = client.post("/api/projects/import/full",
                    files={"file": ("bad.zip", buf.getvalue(),
                                    "application/zip")})
    assert r.status_code == 400


def test_import_project_name_uniqueness():
    d1 = _import_fixture()
    d2 = _import_fixture()
    p1, p2 = d1["project_id"], d2["project_id"]
    assert p1 != p2
    db = SessionLocal()
    try:
        n1 = db.query(Project).filter(Project.id == p1).first().name
        n2 = db.query(Project).filter(Project.id == p2).first().name
        assert n1 != n2
    finally:
        db.close()


def test_import_rejects_secret_key_in_webhooks():
    """Если в webhooks.json есть secret_key — импорт падает 400."""
    with zipfile.ZipFile(FIXTURE) as z:
        members = {n: z.read(n) for n in z.namelist()}
    members["webhooks.json"] = json.dumps([{
        "old_id": 1, "url": "https://x/h",
        "event_type": "annotation.saved",
        "active": True, "secret_key": "leaked-secret",
    }]).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, data in members.items():
            z.writestr(n, data)
    r = client.post("/api/projects/import/full",
                    files={"file": ("bad.zip", buf.getvalue(),
                                    "application/zip")})
    assert r.status_code == 400
    assert "secret_key" in r.text


def test_import_streams_inactive():
    data = _import_fixture()
    pid = data["project_id"]
    db = SessionLocal()
    try:
        for s in db.query(Stream).filter(Stream.project_id == pid).all():
            assert s.is_active is False
    finally:
        db.close()


def test_import_webhook_no_secret():
    data = _import_fixture()
    pid = data["project_id"]
    db = SessionLocal()
    try:
        for wh in db.query(Webhook).filter(Webhook.project_id == pid).all():
            assert wh.secret_key is None
    finally:
        db.close()
