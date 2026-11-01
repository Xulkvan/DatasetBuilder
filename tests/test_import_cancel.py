"""[STAGE6-T2] Отмена импорта для всех источников.

Проверяет через inspect.getsource, что каждый импортёр:
  * создаёт cancel_event = threading.Event();
  * кладёт в IMPORT_CANCELS[project_id];
  * передаёт в _process_dataset_zip или _finalize_external_import.

Это не runtime-тест (требует живого HTTP-источника), но защищает
от регрессий: если кто-то забудет cancel_event — тест упадёт.
"""
import inspect

import pytest


_ENDPOINTS = [
    ("import_url",            "app"),
    ("import_roboflow",       "app"),
    ("import_supervisely",    "app"),
    ("import_local_folder",   "app"),
    ("import_labelbox",       "app"),
    ("import_scale",          "app"),
    ("import_darwin",         "app"),
]


@pytest.mark.parametrize("fn_name,module_name", _ENDPOINTS)
def test_import_endpoint_registers_cancel_event(fn_name, module_name):
    import app as app_mod
    fn = getattr(app_mod, fn_name, None)
    assert fn is not None, f"{module_name}.{fn_name} not found"
    src = inspect.getsource(fn)
    assert "IMPORT_CANCELS" in src, (
        f"{fn_name}: IMPORT_CANCELS не используется — отмена не работает")
    assert "threading.Event" in src, (
        f"{fn_name}: threading.Event не создаётся")
    assert "cancel_event" in src, (
        f"{fn_name}: cancel_event не передаётся")


def test_import_cancel_endpoint():
    """POST /api/import/cancel ставит флаг для всех активных импортов."""
    from fastapi.testclient import TestClient
    from app import app
    client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})
    r = client.post("/api/import/cancel")
    assert r.status_code == 200
    assert r.json().get("status") == "cancelling"


def test_import_cancels_dict_is_isolated():
    """IMPORT_CANCELS должен быть dict — изолированные флаги на проект."""
    from app import IMPORT_CANCELS
    assert isinstance(IMPORT_CANCELS, dict)
