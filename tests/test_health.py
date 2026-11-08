"""[STAGE4-F-08] Health-check, Prometheus metrics, JSON logging."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def local_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "stage4.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


def test_health_returns_disk_ffmpeg_model(local_client):
    """[PATCH:STAGE4-F-08] /api/health возвращает все 5 полей + version."""
    r = local_client.get("/api/health")
    assert r.status_code == 200, r.text
    d = r.json()
    for key in ("status", "db", "disk", "ffmpeg", "model", "version"):
        assert key in d, f"missing health field: {key}"
    assert isinstance(d["db"], bool)
    assert isinstance(d["disk"], bool)
    assert isinstance(d["ffmpeg"], bool)
    assert isinstance(d["model"], bool)
    assert d["status"] in ("ok", "degraded")


def test_health_db_ok(local_client):
    """[PATCH:STAGE4-F-08] db=True в рабочем окружении."""
    r = local_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["db"] is True


def test_metrics_endpoint_returns_prometheus_format(local_client):
    """[PATCH:STAGE4-F-08] /api/metrics -> Prometheus-формат (# HELP / # TYPE)."""
    r = local_client.get("/api/metrics")
    if r.status_code == 404:
        pytest.skip("prometheus-fastapi-instrumentator not installed")
    assert r.status_code == 200, r.text
    text = r.text
    assert "# HELP" in text or "# TYPE" in text, \
        f"metrics output does not look like Prometheus: {text[:200]}"


def test_metrics_endpoint_public(local_client):
    """[PATCH:STAGE4-F-08] /api/metrics доступен без авторизации."""
    r = local_client.get("/api/metrics")
    if r.status_code == 404:
        pytest.skip("prometheus-fastapi-instrumentator not installed")
    assert r.status_code == 200


def test_json_log_file_created(monkeypatch, tmp_path):
    """[PATCH:STAGE4-F-08] log_status -> logs/app.jsonl."""
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    from logger import log_status, _reset_json_loggers
    _reset_json_loggers()
    log_status("info", "test", "stage4 json log test")
    expected = os.path.join(str(tmp_path), "logs", "app.jsonl")
    assert os.path.exists(expected), f"JSON log not created at {expected}"
    with open(expected, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert lines, "JSON log is empty"
    import json as _j
    entry = _j.loads(lines[-1])
    assert entry.get("category") == "test"
    assert entry.get("message") == "stage4 json log test"
    assert "ts" in entry
    assert "level" in entry


def test_image_upload_increments_counter(monkeypatch, tmp_path):
    """[PATCH:STAGE4-F-08] images_uploaded_total растёт после upload."""
    try:
        from prometheus_client import REGISTRY
    except ImportError:
        pytest.skip("prometheus_client not installed")

    import importlib as _il
    from io import BytesIO
    from PIL import Image as _PILImage

    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "cnt.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import config as _cfg
    _il.reload(_cfg)
    import app as app_mod
    _il.reload(app_mod)

    client = TestClient(app_mod.app)
    r = client.post("/api/projects",
                    data={"name": "cnt_test", "object_type": "pig",
                          "object_class": "pig"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    def _sample():
        for metric in REGISTRY.collect():
            for s in metric.samples:
                if s.name == "images_uploaded_total":
                    return s.value
        return None

    before = _sample() or 0

    buf = BytesIO()
    _PILImage.new("RGB", (64, 64), (100, 100, 100)).save(buf, format="JPEG")
    buf.seek(0)
    r = client.post(
        f"/api/projects/{pid}/images",
        files={"file": ("test.jpg", buf, "image/jpeg")},
    )
    assert r.status_code == 200, r.text

    after = _sample() or 0
    assert after > before, \
        f"images_uploaded_total did not grow: {before} -> {after}"
