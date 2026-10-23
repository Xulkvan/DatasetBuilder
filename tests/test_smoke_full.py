"""[STAGE1-D:test-smoke] Smoke-тест полного цикла."""
from datetime import datetime
from fastapi.testclient import TestClient
from app import app, SessionLocal, Project

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def test_smoke_project_create_and_list():
    db = SessionLocal()
    try:
        p = Project(name="smoke_" + datetime.utcnow().strftime("%H%M%S"),
                    created_at=datetime.utcnow(), is_deleted=False,
                    object_class="pig", object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        pid = p.id
    finally:
        db.close()
    r = client.get("/api/projects")
    assert r.status_code == 200
    names = [x["id"] for x in r.json()]
    assert pid in names


def test_smoke_version():
    r = client.get("/api/version")
    assert r.status_code == 200
    assert "version" in r.json()
