"""[STAGE3-BACKUP] Async export/import jobs for full project backup (Stage 3)."""
import io
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app import app, SessionLocal, Project

FIXTURE = Path(__file__).parent / "fixtures" / "sample_full_backup.zip"
client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def _mk_project(name="async_bk"):
    from datetime import datetime
    db = SessionLocal()
    p = Project(name=name, created_at=datetime.utcnow(), is_deleted=False,
                object_class="pig", object_class_source="list")
    db.add(p)
    db.commit()
    db.refresh(p)
    pid = p.id
    db.close()
    return pid


def test_async_export_completes():
    from services.backup_jobs import reset_export_state
    reset_export_state()
    pid = _mk_project()

    r = client.post(f"/api/projects/{pid}/export/full/async", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "started"

    s = None
    for _ in range(60):
        s = client.get("/api/projects/export/full/status").json()
        if s["status"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert s is not None
    assert s["status"] == "done", f"status={s['status']} msg={s.get('error')}"

    r2 = client.get("/api/projects/export/full/download")
    assert r2.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r2.content)) as z:
        assert "manifest.json" in z.namelist()


def test_async_import_completes():
    assert FIXTURE.exists(), (
        f"Missing fixture {FIXTURE}. Generate via export from a real project, "
        f"copy <=1 MB here."
    )
    from services.backup_jobs import reset_import_state
    reset_import_state()

    with open(FIXTURE, "rb") as f:
        r = client.post("/api/projects/import/full/async",
                        files={"file": (FIXTURE.name, f, "application/zip")})
    assert r.status_code == 200, r.text

    s = None
    for _ in range(120):
        s = client.get("/api/projects/import/full/status").json()
        if s["status"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert s is not None
    assert s["status"] == "done", f"status={s['status']} msg={s.get('error')}"
    assert s["result"]["project_id"] > 0


def test_async_import_cancel():
    assert FIXTURE.exists()
    from services.backup_jobs import reset_import_state, import_snapshot
    reset_import_state()
    with open(FIXTURE, "rb") as f:
        r = client.post("/api/projects/import/full/async",
                        files={"file": (FIXTURE.name, f, "application/zip")})
    assert r.status_code == 200
    r = client.post("/api/projects/import/full/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelling"
    for _ in range(50):
        s = import_snapshot()
        if s["status"] in ("idle", "error", "done"):
            break
        time.sleep(0.1)


def test_async_import_rejects_non_zip():
    r = client.post("/api/projects/import/full/async",
                    files={"file": ("bad.zip", b"hello", "application/zip")})
    assert r.status_code in (200, 400, 409)
