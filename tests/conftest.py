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
