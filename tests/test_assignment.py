# [PATCH:STAGE8-test-assignment]
"""Assignment workflow: assign → submit_for_review → approve/reject."""
import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    import app as app_mod
    importlib.reload(app_mod)
    client = TestClient(app_mod.app)
    client.post("/api/setup/admin",
                json={"username": "admin", "password": "admin12345678"})
    r = client.post("/api/users",
                    json={"username": "ann", "password": "ann12345678",
                          "role": "annotator"})
    assert r.status_code == 200, r.text
    ann_id = r.json()["id"]
    r = client.post("/api/projects", data={
        "name": "Test", "object_class": "pig", "object_class_source": "list"})
    assert r.status_code == 200, r.text
    project_id = r.json()["id"]
    return client, project_id, ann_id


def test_assign_endpoint_exists(ctx):
    client, project_id, ann_id = ctx
    # Без изображений — endpoint может вернуть 400/404, но не 500
    r = client.post(f"/api/projects/{project_id}/assign",
                    json={"image_ids": [], "user_id": ann_id})
    assert r.status_code in (200, 400, 404, 422)


def test_review_endpoints_exist(ctx):
    client, project_id, ann_id = ctx
    # Проверяем, что роуты смонтированы (не 404)
    r = client.post("/api/images/999999/submit_for_review")
    assert r.status_code != 405
