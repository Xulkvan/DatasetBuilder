"""Тесты для async backup (STAGE2_BACKUP_SEC)."""
import os
import time
import zipfile

from fastapi.testclient import TestClient

from app import app
from services.backup_jobs import reset_export_state, reset_import_state

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def test_async_export_status_404_when_idle():
    reset_export_state()
    r = client.get("/api/projects/export/full/status")
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["key"] == "error.noActiveExport"


def test_async_import_removes_tempfile(monkeypatch, tmp_path):
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("dummy.txt", "x")

    captured = {}

    def fake_import(db, path):
        captured["zip_path"] = path
        return {"project_id": 1, "counts": {}, "warnings": []}

    monkeypatch.setattr("services.backup_service.import_full_project", fake_import)

    import services.backup_jobs as _bj
    from database import SessionLocal

    reset_import_state()
    _bj.start_import_thread(SessionLocal, str(zip_path), requested_by="test")

    # finally в _worker сначала удаляет zip, затем ставит IMPORT_THREAD=None.
    # Ждём именно IMPORT_THREAD is None — это гарантирует, что cleanup уже прошёл.
    for _ in range(200):
        if _bj.IMPORT_THREAD is None and _bj.IMPORT_STATE["status"] in ("done", "error"):
            break
        time.sleep(0.02)

    assert _bj.IMPORT_STATE["status"] == "done", _bj.IMPORT_STATE
    assert captured["zip_path"] == str(zip_path)
    assert not os.path.exists(zip_path), "temp zip not removed"
