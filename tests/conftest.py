"""Изолированное окружение для тестов: временная SQLite-БД и DATA_ROOT.

ВАЖНО: этот файл выполняется pytest'ом ДО первого import app.
Все os.environ выставляются здесь, чтобы app.py поднялся на чистой БД
и не тронул реальную data/dataset.db.
"""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="pdb_test_")

os.environ["DB_ENGINE"] = "sqlite"
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["DATA_ROOT"] = _TMP
os.environ["DEBUG"] = "0"
os.environ["MAX_UPLOAD_MB"] = "10"

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# [STAGE6:test-fixes] 1) CSRF: все TestClient в тестах должны слать
# X-Requested-With, иначе SecurityMiddleware отклоняет POST/PUT/DELETE
# с 403 "CSRF check failed". Патчим TestClient.__init__ один раз —
# действует для всех тестов без правки каждого файла.
def _patch_testclient_csrf():
    try:
        from fastapi.testclient import TestClient as _TC
    except ImportError:
        return
    if getattr(_TC.__init__, "_csrf_patched", False):
        return
    _orig = _TC.__init__
    def _patched(self, *args, **kwargs):
        h = dict(kwargs.get("headers") or {})
        if not any(k.lower() == "x-requested-with" for k in h):
            h["X-Requested-With"] = "DatasetBuilder"
        kwargs["headers"] = h
        _orig(self, *args, **kwargs)
    _patched._csrf_patched = True
    _TC.__init__ = _patched


_patch_testclient_csrf()


import pytest as _pytest


# [STAGE6:test-fixes] 2) clean_auth_db: очищает users+sessions перед тестом.
# Иначе test_auth падает на shared БД, если другой тест уже создал admin.
@_pytest.fixture
def clean_auth_db():
    try:
        from database import SessionLocal
        from models import User, Session as SessionOrm
    except Exception:
        yield
        return
    db = SessionLocal()
    try:
        try:
            db.query(SessionOrm).delete()
        except Exception:
            db.rollback()
        try:
            db.query(User).delete()
        except Exception:
            db.rollback()
        db.commit()
    finally:
        db.close()
    try:
        from services.auth_service import invalidate_setup_cache
        invalidate_setup_cache()
    except Exception:
        pass
    yield
