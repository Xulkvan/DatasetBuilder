"""[PATCH:STAGE5-T10-fix] F-18 + C11: 409 error.importCancelled при отмене.

Fix: предыдущая версия теста monkeypatch-ила `threading.Event` на
pre-set класс. Это ломало `starlette.TestClient` (он сам использует
Event внутри `start_blocking_portal`) → RuntimeError: threads can only
be started once.

Теперь monkeypatch-им сам `_process_dataset_zip`: он устанавливает
cancel_event ПЕРЕД тем, как вызвать оригинал. Оригинал в первом
витке hot-loop видит set() и кидает HTTPException(409).
"""
import io
import zipfile

from fastapi.testclient import TestClient

from app import app, SessionLocal, Project

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def _mk_project(name):
    from datetime import datetime
    db = SessionLocal()
    try:
        p = Project(name=name, created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        return p.id
    finally:
        db.close()


def _make_minimal_zip():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (100, 100, 100)).save(buf, format="JPEG")
    img_bytes = buf.getvalue()
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("a.jpg", img_bytes)
    return zbuf.getvalue()


class TestImportCancel409:
    def test_import_cancel_returns_409(self, monkeypatch):
        """Импорт с уже-отменённым cancel_event -> 409 error.importCancelled.

        Эмулируем «пользователь нажал Отменить прямо перед стартом
        _process_dataset_zip»: устанавливаем event до реальной работы.
        """
        pid = _mk_project("t10_cancel")

        import app as app_mod
        _orig = app_mod._process_dataset_zip

        def _wrapped(zip_path, project_id, db,
                     cancel_event=None, source="upload"):
            if cancel_event is not None:
                cancel_event.set()
            return _orig(zip_path, project_id, db, cancel_event, source)

        monkeypatch.setattr(app_mod, "_process_dataset_zip", _wrapped)

        zip_bytes = _make_minimal_zip()
        r = client.post(
            f"/api/projects/{pid}/import",
            files={"file": ("test.zip", zip_bytes, "application/zip")},
        )
        assert r.status_code == 409, r.text
        detail = r.json().get("detail", {})
        assert isinstance(detail, dict), f"detail not dict: {detail!r}"
        assert detail.get("key") == "error.importCancelled", detail

    def test_import_cancel_endpoint(self):
        r = client.post("/api/import/cancel")
        assert r.status_code == 200
        assert r.json().get("status") == "cancelling"

    def test_import_cancels_dict_isolated(self):
        from app import IMPORT_CANCELS
        assert isinstance(IMPORT_CANCELS, dict)
