"""[STAGE3] Full backup strips credentials from Stream.url on export.

Regression: export писал `rtsp://user:pass@host/path` verbatim, но
import_full_project отклоняет архивы, у которых streams.json содержит
URL с credentials (services/backup_validate.py). Итог: любой проект
с аутентифицированным RTSP-стримом был НЕВОССТАНОВИМ.

Fix: strip user:pass перед записью streams.json + manifest warning
"credentials stripped from URL". После импорта URL всё равно требует
ручного ввода креденшелов (ADR-0011).
"""
import importlib
import io
import json
import zipfile
from datetime import datetime

from fastapi.testclient import TestClient


def _reload_app(monkeypatch, tmp_path, db_name):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / db_name))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("CSRF_STRICT", "0")
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return app_mod


def _mk_project(app_mod, name):
    db = app_mod.SessionLocal()
    try:
        p = app_mod.Project(
            name=name, created_at=datetime.utcnow(),
            is_deleted=False, object_class="pig",
            object_class_source="list",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        return int(p.id)
    finally:
        db.close()


def _reset_import_limiter():
    try:
        from services.rate_limiter import _limiter_import
        with _limiter_import._lock:
            _limiter_import._buckets.clear()
    except Exception:
        pass


def test_export_strips_stream_credentials(monkeypatch, tmp_path, clean_auth_db):
    app_mod = _reload_app(monkeypatch, tmp_path, "streams_export.db")
    from models import Stream
    db = app_mod.SessionLocal()
    try:
        pid = _mk_project(app_mod, "streams_export")
        db.add(Stream(
            project_id=pid, url="rtsp://user:pass@cam.example/1",
            name="cam1", is_active=False, capture_fps=1.0,
        ))
        db.commit()
    finally:
        db.close()

    client = TestClient(app_mod.app, headers={"X-Requested-With": "DatasetBuilder"})
    r = client.get(f"/api/projects/{pid}/export/full?include_streams=true")
    assert r.status_code == 200, r.text

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        streams = json.loads(z.read("streams.json"))
        manifest = json.loads(z.read("manifest.json"))

    assert len(streams) == 1
    url = streams[0]["url"]
    assert "user:pass@" not in url, url
    assert url.startswith("rtsp://cam.example/"), url
    warnings = manifest.get("warnings") or []
    assert any("credentials stripped" in w for w in warnings), warnings


def test_exported_backup_with_stream_is_importable(monkeypatch, tmp_path, clean_auth_db):
    """Round-trip: export с credentials → import НЕ отклоняется."""
    _reset_import_limiter()
    app_mod = _reload_app(monkeypatch, tmp_path, "streams_roundtrip.db")
    from models import Stream
    db = app_mod.SessionLocal()
    try:
        pid = _mk_project(app_mod, "streams_roundtrip")
        db.add(Stream(
            project_id=pid, url="rtsp://u:p@cam2.example/stream",
            name="cam2", is_active=False, capture_fps=2.0,
        ))
        db.commit()
    finally:
        db.close()

    client = TestClient(app_mod.app, headers={"X-Requested-With": "DatasetBuilder"})
    r = client.get(f"/api/projects/{pid}/export/full?include_streams=true")
    assert r.status_code == 200, r.text
    backup_bytes = r.content

    _reset_import_limiter()
    r = client.post(
        "/api/projects/import/full",
        files={"file": ("streams_backup.zip", backup_bytes, "application/zip")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert int(body["project_id"]) != int(pid)
    assert int(body["counts"]["streams"]) == 1
