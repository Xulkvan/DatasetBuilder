"""[STAGE3] REQUIRE_ANNOTATION_REVISION=1 forces `revision` on save.

Regression: без флага клиенты могли не слать `revision` и молча
перезаписывать параллельные правки. Когда REQUIRE_ANNOTATION_REVISION=1
(типично для team mode), POST /api/images/{id}/annotations без
`revision` ДОЛЖЕН возвращать 400 error.revisionRequired.

Default REQUIRE_ANNOTATION_REVISION=0 сохраняет backward compat:
старые клиенты / SDK продолжают работать без `revision`.
"""
import importlib
from datetime import datetime

from fastapi.testclient import TestClient


_PAYLOAD = [{
    "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2,
    "label": "pig", "keypoints": [],
}]


def _reload_app(monkeypatch, tmp_path, required_revision, db_name):
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / db_name))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("CSRF_STRICT", "0")
    monkeypatch.setenv("REQUIRE_ANNOTATION_REVISION", required_revision)
    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)
    return app_mod


def _mk_image(app_mod, filename):
    db = app_mod.SessionLocal()
    try:
        p = app_mod.Project(
            name=f"t3rev_{filename}",
            created_at=datetime.utcnow(),
            is_deleted=False,
            object_class="pig",
            object_class_source="list",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        im = app_mod.ImageModel(
            project_id=p.id, filename=filename,
            path="/tmp/_t3rev_" + filename,
            width=640, height=640, is_deleted=False, revision=1,
        )
        db.add(im)
        db.commit()
        db.refresh(im)
        return int(im.id)
    finally:
        db.close()


def test_revision_required_400_when_flag_set(monkeypatch, tmp_path, clean_auth_db):
    app_mod = _reload_app(monkeypatch, tmp_path, "1", "rev_flag1.db")
    client = TestClient(app_mod.app, headers={"X-Requested-With": "DatasetBuilder"})
    iid = _mk_image(app_mod, "a.jpg")
    r = client.post(f"/api/images/{iid}/annotations", json=_PAYLOAD)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", {})
    assert isinstance(detail, dict), detail
    assert detail.get("key") == "error.revisionRequired", detail


def test_revision_accepted_when_flag_set(monkeypatch, tmp_path, clean_auth_db):
    app_mod = _reload_app(monkeypatch, tmp_path, "1", "rev_flag1b.db")
    client = TestClient(app_mod.app, headers={"X-Requested-With": "DatasetBuilder"})
    iid = _mk_image(app_mod, "b.jpg")
    r = client.post(f"/api/images/{iid}/annotations?revision=1", json=_PAYLOAD)
    assert r.status_code == 200, r.text


def test_no_revision_ok_when_flag_unset(monkeypatch, tmp_path, clean_auth_db):
    app_mod = _reload_app(monkeypatch, tmp_path, "0", "rev_flag0.db")
    client = TestClient(app_mod.app, headers={"X-Requested-With": "DatasetBuilder"})
    iid = _mk_image(app_mod, "c.jpg")
    r = client.post(f"/api/images/{iid}/annotations", json=_PAYLOAD)
    assert r.status_code == 200, r.text
