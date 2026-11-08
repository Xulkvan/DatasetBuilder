"""[PATCH:STAGE5-T4] C26: v2_train_async использует python -c, не CLI yolo."""
import importlib
import json
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def team_client(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t4.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("API_KEY", "test_key_123")
    monkeypatch.setenv("CSRF_STRICT", "0")
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    c = TestClient(app_mod.app)
    c.post("/api/setup/admin",
           json={"username": "admin", "password": "admin12345678"})
    return c


def _wait_task(client, tid, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = client.get(
            f"/api/v2/tasks/{tid}",
            headers={"Authorization": "Bearer test_key_123"},
        ).json()
        if s.get("status") in ("done", "error", "stopped"):
            return s
        time.sleep(0.1)
    return {"status": "timeout"}


class TestV2Train:
    def test_v2_train_uses_python_c(self, team_client, monkeypatch):
        captured = {}

        def fake_run(args, run_dir, run_id, custom_name):
            captured["args"] = list(args)

        import services.train_service as tsvc
        monkeypatch.setattr(tsvc, "run_training_thread", fake_run)

        from app import SessionLocal
        from models import ImageModel, Annotation

        r = team_client.post("/api/projects",
                             data={"name": "t4_p", "object_class": "pig"})
        pid = r.json()["id"]
        db = SessionLocal()
        try:
            im = ImageModel(project_id=pid, filename="x.jpg",
                            path="/tmp/_t4_x.jpg",
                            width=640, height=640, is_deleted=False)
            db.add(im); db.commit(); db.refresh(im)
            db.add(Annotation(image_id=im.id, x=0.1, y=0.1,
                              w=0.2, h=0.2, label="pig"))
            db.commit()
        finally:
            db.close()

        r = team_client.post(
            f"/api/v2/projects/{pid}/train",
            json={"epochs": 1, "base_model": "yolov8n.pt", "task": "detect"},
            headers={"Authorization": "Bearer test_key_123"},
        )
        assert r.status_code == 202, r.text
        tid = r.json()["task_id"]

        s = _wait_task(team_client, tid)
        assert s.get("status") == "done", s
        assert "result" in s and "run_id" in s["result"]

        assert "args" in captured, "run_training_thread не вызван"
        args = captured["args"]
        assert args[0] != "yolo", f"v2_train использует CLI yolo: {args}"
        assert "-c" in args or "--train-worker" in args, (
            f"v2_train должен звать python -c: {args}"
        )
        if "-c" in args:
            cfg = json.loads(args[-1])
            assert cfg["model"].endswith(".pt")
            assert "kwargs" in cfg
            assert cfg["kwargs"].get("device") == "cpu"

    def test_v2_train_task_not_found(self, team_client):
        r = team_client.get(
            "/api/v2/tasks/nonexistent-task-id",
            headers={"Authorization": "Bearer test_key_123"},
        )
        assert r.status_code == 404
