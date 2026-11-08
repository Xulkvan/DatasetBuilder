"""[PATCH:STAGE2] Тесты Этапа 2.

Покрывает C1, C27, F-02, C2, C3, C26, F-11.
"""
import importlib
import json
import time
import zipfile
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def local_client(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "s2.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("CSRF_STRICT", "0")
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return TestClient(app_mod.app)


@pytest.fixture
def team_client(monkeypatch, tmp_path, clean_auth_db):
    monkeypatch.setenv("AUTH_MODE", "team")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "s2t.db"))
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


def _mk_project(db, name):
    from models import Project
    p = Project(name=name, created_at=datetime.utcnow(),
                is_deleted=False, object_class="pig",
                object_class_source="list")
    db.add(p); db.commit(); db.refresh(p)
    return p.id


def _mk_image(db, pid, fname="a.jpg"):
    from models import ImageModel
    im = ImageModel(project_id=pid, filename=fname,
                    path="/tmp/_s2_" + fname,
                    width=640, height=640, is_deleted=False,
                    created_at=datetime.utcnow())
    db.add(im); db.commit(); db.refresh(im)
    return im.id


def _mk_annotation(db, iid, **kw):
    from models import Annotation
    a = Annotation(image_id=iid,
                   x=kw.get("x", 0.1), y=kw.get("y", 0.1),
                   w=kw.get("w", 0.2), h=kw.get("h", 0.2),
                   label="pig",
                   behavior=kw.get("behavior"),
                   animal_id=kw.get("animal_id"))
    db.add(a); db.commit(); db.refresh(a)
    return a.id


# ===========================================================================
# C1
# ===========================================================================
class TestC1WebhookAsync:
    def test_webhook_does_not_block_save(self, local_client):
        from app import SessionLocal
        from models import Webhook
        db = SessionLocal()
        try:
            pid = _mk_project(db, "wh_async")
            iid = _mk_image(db, pid)
            db.add(Webhook(project_id=pid,
                           url="http://127.0.0.1:65534/hook",
                           event_type="annotation.saved",
                           secret_key="", active=True,
                           created_at=datetime.utcnow()))
            db.commit()
        finally:
            db.close()

        payload = [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2,
                    "label": "pig", "keypoints": []}]
        t0 = time.perf_counter()
        r = local_client.post(f"/api/images/{iid}/annotations", json=payload)
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200, r.text
        assert elapsed < 1.0, (
            f"save_annotations заблокирован webhook'ом: {elapsed:.2f}s")


# ===========================================================================
# C27
# ===========================================================================
class TestC27PurgeDependencies:
    def test_purge_removes_webhook_and_version(self, local_client):
        from app import SessionLocal
        from models import (
            Webhook, DatasetVersion, Stream, ProjectKeypointSchema,
        )
        from services.project_service import _purge_projects
        db = SessionLocal()
        try:
            pid = _mk_project(db, "c27_purge")
            db.add(Webhook(project_id=pid, url="http://x.test/h",
                           event_type="annotation.saved",
                           secret_key="", active=True,
                           created_at=datetime.utcnow()))
            db.add(DatasetVersion(project_id=pid, hash="x"*32,
                                  created_at=datetime.utcnow(),
                                  image_count=1, annotation_count=1))
            db.add(Stream(project_id=pid, url="rtsp://x", name="s",
                          is_active=False))
            db.add(ProjectKeypointSchema(project_id=pid,
                                         schema_json='[{"name":"nose"}]'))
            db.commit()

            _purge_projects(db, [pid])

            assert db.query(Webhook).filter(
                Webhook.project_id == pid).count() == 0
            assert db.query(DatasetVersion).filter(
                DatasetVersion.project_id == pid).count() == 0
            assert db.query(Stream).filter(
                Stream.project_id == pid).count() == 0
            assert db.query(ProjectKeypointSchema).filter(
                ProjectKeypointSchema.project_id == pid).count() == 0
        finally:
            db.close()


# ===========================================================================
# F-02
# ===========================================================================
class TestF02Retention:
    def test_cleanup_expired_data(self, local_client):
        from app import SessionLocal
        from services.trash_service import cleanup_expired_data
        from models import Project, ImageModel
        db = SessionLocal()
        try:
            pid = _mk_project(db, "f02_ret")
            db.query(Project).filter(Project.id == pid).update(
                {"data_retention_days": 1})
            db.commit()
            old_id = _mk_image(db, pid, "old.jpg")
            db.query(ImageModel).filter(ImageModel.id == old_id).update(
                {"created_at": datetime.utcnow() - timedelta(days=2)})
            db.commit()
            new_id = _mk_image(db, pid, "new.jpg")

            n = cleanup_expired_data(db)
            assert n >= 1
            assert db.query(ImageModel).filter(
                ImageModel.id == old_id).count() == 0
            assert db.query(ImageModel).filter(
                ImageModel.id == new_id).count() == 1
        finally:
            db.close()

    def test_retention_zero_disabled(self, local_client):
        from app import SessionLocal
        from services.trash_service import cleanup_expired_data
        from models import ImageModel
        db = SessionLocal()
        try:
            pid = _mk_project(db, "f02_zero")
            iid = _mk_image(db, pid)
            db.query(ImageModel).filter(ImageModel.id == iid).update(
                {"created_at": datetime.utcnow() - timedelta(days=365)})
            db.commit()
            cleanup_expired_data(db)
            assert db.query(ImageModel).filter(
                ImageModel.id == iid).count() == 1
        finally:
            db.close()

    def test_retention_respects_is_deleted(self, local_client):
        from app import SessionLocal
        from services.trash_service import cleanup_expired_data
        from models import Project, ImageModel
        db = SessionLocal()
        try:
            pid = _mk_project(db, "f02_del")
            db.query(Project).filter(Project.id == pid).update(
                {"data_retention_days": 1})
            db.commit()
            iid = _mk_image(db, pid, "del.jpg")
            db.query(ImageModel).filter(ImageModel.id == iid).update({
                "created_at": datetime.utcnow() - timedelta(days=2),
                "is_deleted": True,
                "deleted_at": datetime.utcnow() - timedelta(days=1),
            })
            db.commit()
            cleanup_expired_data(db)
            # soft-deleted не должны удаляться retention-ом (у них свой TTL)
            assert db.query(ImageModel).filter(
                ImageModel.id == iid).count() == 1
        finally:
            db.close()


# ===========================================================================
# C2
# ===========================================================================
class TestC2CsvEndpoints:
    def test_stats_csv_exists(self, local_client):
        from app import SessionLocal
        db = SessionLocal()
        try:
            pid = _mk_project(db, "c2_stats")
            iid = _mk_image(db, pid)
            _mk_annotation(db, iid)
        finally:
            db.close()
        r = local_client.get(f"/api/projects/{pid}/stats.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        assert "filename" in r.text

    def test_files_csv_exists(self, local_client):
        from app import SessionLocal
        db = SessionLocal()
        try:
            pid = _mk_project(db, "c2_files")
            _mk_image(db, pid)
        finally:
            db.close()
        r = local_client.get(f"/api/projects/{pid}/files.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")

    def test_boxes_csv_exists(self, local_client):
        from app import SessionLocal
        db = SessionLocal()
        try:
            pid = _mk_project(db, "c2_boxes")
            iid = _mk_image(db, pid)
            _mk_annotation(db, iid, behavior="eat", animal_id=5)
        finally:
            db.close()
        r = local_client.get(f"/api/projects/{pid}/boxes.csv")
        assert r.status_code == 200
        assert "eat" in r.text

    def test_stats_csv_applies_filters(self, local_client):
        from app import SessionLocal
        db = SessionLocal()
        try:
            pid = _mk_project(db, "c2_filter")
            iid1 = _mk_image(db, pid, "annot.jpg")
            _mk_annotation(db, iid1)
            iid2 = _mk_image(db, pid, "empty.jpg")
        finally:
            db.close()
        r = local_client.get(
            f"/api/projects/{pid}/stats.csv?filter=unannotated")
        assert r.status_code == 200
        assert "empty.jpg" in r.text
        assert "annot.jpg" not in r.text


# ===========================================================================
# C3
# ===========================================================================
class TestC3V2ExportDownload:
    def test_v2_export_download_with_bearer(self, team_client):
        r = team_client.post("/api/projects",
                             data={"name": "c3_p", "object_class": "pig"})
        pid = r.json()["id"]
        r = team_client.get(
            f"/api/v2/projects/{pid}/export/yolo/download",
            headers={"Authorization": "Bearer test_key_123"},
        )
        # 200 / 404 (нет images) / 500 — но не 401/403
        assert r.status_code not in (401, 403), r.text

    def test_v2_export_download_without_bearer(self, team_client):
        r = team_client.post("/api/projects",
                             data={"name": "c3_p2", "object_class": "pig"})
        pid = r.json()["id"]
        r = team_client.get(f"/api/v2/projects/{pid}/export/yolo/download")
        assert r.status_code in (401, 403), r.text


# ===========================================================================
# C26
# ===========================================================================
class TestC26V2Train:
    def test_v2_train_uses_python_c(self, team_client, monkeypatch):
        """v2_train_async должен звать python -c, а не CLI yolo."""
        captured = {}

        def fake_run(args, run_dir, run_id, custom_name):
            captured["args"] = list(args)
            captured["run_dir"] = run_dir
            captured["run_id"] = run_id

        import services.train_service as tsvc
        monkeypatch.setattr(tsvc, "run_training_thread", fake_run)

        from app import SessionLocal
        from models import ImageModel, Annotation
        db = SessionLocal()
        try:
            r = team_client.post("/api/projects",
                                 data={"name": "c26_p",
                                       "object_class": "pig"})
            pid = r.json()["id"]
            im = ImageModel(project_id=pid, filename="x.jpg",
                            path="/tmp/_c26_x.jpg",
                            width=640, height=640, is_deleted=False)
            db.add(im); db.commit(); db.refresh(im)
            db.add(Annotation(image_id=im.id, x=0.1, y=0.1,
                              w=0.2, h=0.2, label="pig"))
            db.commit()
        finally:
            db.close()

        r = team_client.post(
            f"/api/v2/projects/{pid}/train",
            json={"epochs": 1, "base_model": "yolov8n.pt",
                  "task": "detect"},
            headers={"Authorization": "Bearer test_key_123"},
        )
        assert r.status_code == 202, r.text
        tid = r.json()["task_id"]

        for _ in range(100):
            time.sleep(0.1)
            s = team_client.get(
                f"/api/v2/tasks/{tid}",
                headers={"Authorization": "Bearer test_key_123"},
            ).json()
            if s.get("status") in ("done", "error"):
                break

        assert "args" in captured, "run_training_thread не вызван"
        args = captured["args"]
        assert args[0] != "yolo", (
            f"v2_train всё ещё использует CLI 'yolo': {args}")
        assert "-c" in args or "--train-worker" in args, (
            f"v2_train должен использовать python -c: {args}")
        if "-c" in args:
            cfg = json.loads(args[-1])
            assert cfg["model"].endswith(".pt")


# ===========================================================================
# F-11
# ===========================================================================
class TestF11PipelineBackup:
    def test_pipeline_replace_creates_backup(self, local_client,
                                              monkeypatch, tmp_path):
        from app import SessionLocal
        import services.pipeline_service as ps

        monkeypatch.setattr(ps, "get_active_model_path",
                            lambda db: "/fake/model.pt")

        class _FakeModel:
            names = {0: "pig"}

        monkeypatch.setattr(ps, "_get_yolo_model", lambda p: _FakeModel())
        monkeypatch.setattr(ps, "_resolve_target_class_ids",
                            lambda m, lbl: {0})
        monkeypatch.setattr(
            ps, "_autolabel_batch_predict",
            lambda paths, m, W, H, ids, lbl, *a, **kw: [
                [] for _ in paths],
        )

        db = SessionLocal()
        try:
            pid = _mk_project(db, "f11_backup")
            iid = _mk_image(db, pid)
            _mk_annotation(db, iid)
        finally:
            db.close()

        db = SessionLocal()
        try:
            r = ps._stage_autolabel(db, pid, mode="replace")
            assert r == "done", r
            with ps.PIPELINE_LOCK:
                bp = ps.PIPELINE_STATE.get("pre_replace_backup")
            assert bp, "backup path not stored in PIPELINE_STATE"
        finally:
            db.close()

    def test_pipeline_rollback_restores_data(self, local_client):
        from app import SessionLocal
        from models import ImageModel, Annotation
        import services.pipeline_service as ps
        from services.backup_service import create_backup

        db = SessionLocal()
        try:
            pid = _mk_project(db, "f11_rb")
            iid = _mk_image(db, pid, "rb.jpg")
            _mk_annotation(db, iid, behavior="eat")
        finally:
            db.close()

        db = SessionLocal()
        try:
            bp_path, _ = create_backup(
                db, pid, prefix="pre_replace_backup")
        finally:
            db.close()

        # эмулируем replace: удаляем разметку
        db = SessionLocal()
        try:
            db.query(Annotation).filter(
                Annotation.image_id == iid).delete()
            db.commit()
        finally:
            db.close()

        with ps.PIPELINE_LOCK:
            ps.PIPELINE_STATE["pre_replace_backup"] = bp_path

        r = local_client.post(f"/api/projects/{pid}/pipeline/rollback")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "ok"
        assert d["restored_images"] >= 1

        db = SessionLocal()
        try:
            restored_imgs = db.query(ImageModel).filter(
                ImageModel.project_id == pid,
                ImageModel.is_deleted.is_(False)).all()
            assert len(restored_imgs) >= 1
            anns = db.query(Annotation).filter(
                Annotation.image_id == restored_imgs[0].id).all()
            assert len(anns) == 1
            assert anns[0].behavior == "eat"
        finally:
            db.close()


# ===========================================================================
# Route permissions
# ===========================================================================
class TestStage2RoutePermissions:
    def test_rollback_rule_present(self):
        from services.route_permissions import match_permission
        perm = match_permission(
            "POST", "/api/projects/42/pipeline/rollback")
        assert perm == "pipeline.run"
