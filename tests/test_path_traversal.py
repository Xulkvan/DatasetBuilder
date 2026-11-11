"""[STAGE5] Path traversal / zip-slip + health + request_id.

Покрывает:
  * _safe_model_path: '..', '/', '\\', NUL, неверные расширения;
  * _safe_extract_zip: '../../evil', абсолютные пути, Windows-drive;
  * validate_user_filename: control chars;
  * /api/health возвращает {status: "ok", db: true} и публичен;
  * X-Request-ID присутствует в ответах и уникален между запросами;
  * log_status принимает request_id (explicit + contextvar).
"""
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.file_service import (
    _safe_model_path, _sanitize_model_name, validate_user_filename,
)


class TestModelPathTraversal:
    def test_dotdot_rejected(self):
        with pytest.raises(HTTPException):
            _safe_model_path("../../etc/passwd")

    def test_slash_rejected(self):
        with pytest.raises(HTTPException):
            _safe_model_path("subdir/model.pt")

    def test_backslash_rejected(self):
        with pytest.raises(HTTPException):
            _safe_model_path("subdir\\model.pt")

    def test_nul_byte_rejected(self):
        with pytest.raises(HTTPException):
            _safe_model_path("model\x00.pt")

    def test_wrong_extension_rejected(self):
        with pytest.raises(HTTPException):
            _safe_model_path("evil.sh")

    def test_missing_extension_rejected(self):
        with pytest.raises(HTTPException):
            _safe_model_path("noextension")

    def test_valid_model_name_accepted(self):
        assert _safe_model_path("yolov8n.pt").endswith("yolov8n.pt")

    def test_valid_onnx_name_accepted(self):
        assert _safe_model_path("my_model.onnx").endswith("my_model.onnx")


class TestSanitizeModelName:
    def test_dotdot_stripped(self):
        name = _sanitize_model_name("../../evil.pt")
        assert ".." not in name
        assert "/" not in name

    def test_extension_added(self):
        assert _sanitize_model_name("mymodel").endswith(".pt")

    def test_empty_returns_empty(self):
        assert _sanitize_model_name("") == ""
        assert _sanitize_model_name("../../..") == ""


class TestUserFilename:
    def test_slash_rejected(self):
        with pytest.raises(HTTPException):
            validate_user_filename("foo/bar.jpg")

    def test_backslash_rejected(self):
        with pytest.raises(HTTPException):
            validate_user_filename("foo\\bar.jpg")

    def test_empty_rejected(self):
        with pytest.raises(HTTPException):
            validate_user_filename("")

    def test_dotdot_rejected(self):
        with pytest.raises(HTTPException):
            validate_user_filename("..")

    def test_dot_rejected(self):
        with pytest.raises(HTTPException):
            validate_user_filename(".")

    def test_trailing_dot_rejected(self):
        with pytest.raises(HTTPException):
            validate_user_filename("photo.")

    def test_valid_accepted(self):
        validate_user_filename("photo.jpg")
        validate_user_filename("with space.jpg")


class TestZipSlip:
    def _evil_zip(self, tmp_path, member_name):
        zpath = tmp_path / "evil.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr(member_name, "pwned")
        return zpath

    def _out(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        return out

    def test_parent_traversal_blocked(self, tmp_path):
        from services.zip_import_service import _safe_extract_zip
        zpath = self._evil_zip(tmp_path, "../../evil.txt")
        out = self._out(tmp_path)
        with zipfile.ZipFile(zpath) as zf:
            with pytest.raises(HTTPException):
                _safe_extract_zip(zf, str(out))
        assert not (tmp_path / "evil.txt").exists()
        assert not (tmp_path.parent / "evil.txt").exists()

    def test_absolute_unix_path_blocked(self, tmp_path):
        from services.zip_import_service import _safe_extract_zip
        zpath = self._evil_zip(tmp_path, "/tmp/_pdb_evil_should_not_exist.txt")
        out = self._out(tmp_path)
        with zipfile.ZipFile(zpath) as zf:
            with pytest.raises(HTTPException):
                _safe_extract_zip(zf, str(out))

    def test_absolute_windows_path_blocked(self, tmp_path):
        from services.zip_import_service import _safe_extract_zip
        zpath = self._evil_zip(tmp_path, "C:\\Windows\\evil.txt")
        out = self._out(tmp_path)
        with zipfile.ZipFile(zpath) as zf:
            with pytest.raises(HTTPException):
                _safe_extract_zip(zf, str(out))

    def test_deep_traversal_blocked(self, tmp_path):
        from services.zip_import_service import _safe_extract_zip
        zpath = self._evil_zip(tmp_path, "../../../../../../etc/passwd")
        out = self._out(tmp_path)
        with zipfile.ZipFile(zpath) as zf:
            with pytest.raises(HTTPException):
                _safe_extract_zip(zf, str(out))

    def test_legit_extraction_works(self, tmp_path):
        from services.zip_import_service import _safe_extract_zip
        zpath = tmp_path / "good.zip"
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("subdir/file.txt", "hello")
            z.writestr("root.txt", "world")
        out = self._out(tmp_path)
        with zipfile.ZipFile(zpath) as zf:
            _safe_extract_zip(zf, str(out))
        assert (out / "subdir" / "file.txt").read_text() == "hello"
        assert (out / "root.txt").read_text() == "world"


# ============================================================================
# health + request_id (5.3 / 5.4)
# ============================================================================

class TestHealthEndpoint:
    def _client(self, monkeypatch, tmp_path, auth_mode):
        import importlib
        monkeypatch.setenv("AUTH_MODE", auth_mode)
        monkeypatch.setenv("DB_ENGINE", "sqlite")
        monkeypatch.setenv("DB_PATH", str(tmp_path / f"h_{auth_mode}.db"))
        monkeypatch.setenv("DATA_ROOT", str(tmp_path))
        import config as _cfg
        importlib.reload(_cfg)
        import app as app_mod
        importlib.reload(app_mod)
        from fastapi.testclient import TestClient
        return TestClient(app_mod.app)

    def test_health_returns_db_ok(self, monkeypatch, tmp_path, clean_auth_db):
        client = self._client(monkeypatch, tmp_path, "local")
        r = client.get("/api/health")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "ok"
        assert d["db"] is True
        assert "version" in d

    def test_health_is_public_in_team_mode(self, monkeypatch, tmp_path, clean_auth_db):
        client = self._client(monkeypatch, tmp_path, "team")
        r = client.get("/api/health")
        assert r.status_code == 200, (
            f"healthcheck должен быть публичным, got {r.status_code}: {r.text[:200]}")


class TestRequestIdHeader:
    def _client(self, monkeypatch, tmp_path):
        import importlib
        monkeypatch.setenv("AUTH_MODE", "local")
        monkeypatch.setenv("DB_ENGINE", "sqlite")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "rid.db"))
        monkeypatch.setenv("DATA_ROOT", str(tmp_path))
        import config as _cfg
        importlib.reload(_cfg)
        import app as app_mod
        importlib.reload(app_mod)
        from fastapi.testclient import TestClient
        return TestClient(app_mod.app)

    def test_request_id_present(self, monkeypatch, tmp_path, clean_auth_db):
        client = self._client(monkeypatch, tmp_path)
        r = client.get("/api/version")
        assert "X-Request-ID" in r.headers
        assert len(r.headers["X-Request-ID"]) == 8

    def test_request_ids_unique_between_calls(self, monkeypatch, tmp_path, clean_auth_db):
        client = self._client(monkeypatch, tmp_path)
        r1 = client.get("/api/version")
        r2 = client.get("/api/version")
        assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]


class TestLoggerRequestId:
    def test_explicit_request_id_in_entry(self):
        from logger import STATUS_LOG, STATUS_LOG_LOCK, log_status
        log_status("info", "test", "explicit rid", request_id="abc12345")
        with STATUS_LOG_LOCK:
            entry = list(STATUS_LOG)[-1]
        assert entry.get("request_id") == "abc12345"

    def test_contextvar_is_used(self):
        from logger import (
            STATUS_LOG, STATUS_LOG_LOCK, log_status, set_request_id,
        )
        set_request_id("xyz98765")
        try:
            log_status("info", "test", "from context")
            with STATUS_LOG_LOCK:
                entry = list(STATUS_LOG)[-1]
            assert entry.get("request_id") == "xyz98765"
        finally:
            set_request_id("")

    def test_absent_request_id(self):
        from logger import (
            STATUS_LOG, STATUS_LOG_LOCK, log_status, set_request_id,
        )
        set_request_id("")
        log_status("info", "test", "no rid")
        with STATUS_LOG_LOCK:
            entry = list(STATUS_LOG)[-1]
        assert "request_id" not in entry
