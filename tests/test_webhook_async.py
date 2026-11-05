"""[PATCH:STAGE5-T1-fix] C1: webhook не блокирует save_annotations.

Acceptance (план, Этап 2):
  * POST /api/images/{id}/annotations при наличии webhook на мёртвый URL
    не блокируется более 1 секунды (fire-and-forget).

Fix: Webhook импортируется из models (в app.py он НЕ ре-экспортируется).
"""
import time
from datetime import datetime

from fastapi.testclient import TestClient

# Модели БД — из models; SessionLocal и app — из app.
from app import app, SessionLocal, Project, ImageModel
from models import Webhook

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})
DEAD_URL = "http://127.0.0.1:65534/hook"


def _mk_project(name):
    db = SessionLocal()
    try:
        p = Project(name=name, created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        return p.id
    finally:
        db.close()


def _mk_image(pid, filename="a.jpg"):
    db = SessionLocal()
    try:
        im = ImageModel(project_id=pid, filename=filename,
                        path="/tmp/_nonexistent_" + filename,
                        width=640, height=640, is_deleted=False)
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


def _mk_webhook(pid, url=DEAD_URL):
    db = SessionLocal()
    try:
        wh = Webhook(project_id=pid, url=url,
                     event_type="annotation.saved",
                     secret_key="", active=True,
                     created_at=datetime.utcnow())
        db.add(wh); db.commit(); db.refresh(wh)
        return wh.id
    finally:
        db.close()


class TestWebhookAsync:
    def test_webhook_does_not_block_save(self):
        pid = _mk_project("t1_wh_async")
        iid = _mk_image(pid)
        _mk_webhook(pid)

        payload = [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2,
                    "label": "pig", "keypoints": []}]
        t0 = time.perf_counter()
        r = client.post(f"/api/images/{iid}/annotations", json=payload)
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200, r.text
        assert elapsed < 1.0, (
            f"save_annotations заблокирован webhook: {elapsed:.2f}s"
        )

    def test_webhook_async_survives_multiple_dead_urls(self):
        pid = _mk_project("t1_wh_async2")
        iid = _mk_image(pid)
        _mk_webhook(pid, url="http://127.0.0.1:65533/hook1")
        _mk_webhook(pid, url="http://127.0.0.1:65532/hook2")
        payload = [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2,
                    "label": "pig", "keypoints": []}]
        r = client.post(f"/api/images/{iid}/annotations", json=payload)
        assert r.status_code == 200
