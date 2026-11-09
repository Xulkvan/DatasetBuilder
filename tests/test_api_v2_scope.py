"""Regression: API v2 project scoping (STAGE1_SEC_V2).

Закрывает IDOR в /api/v2/*: раньше один API_KEY давал доступ ко всем
проектам. Теперь API_KEY может быть JSON-map:
    {"tokenA": {"projects": [1,2]}, "tokenB": {"projects": "*"}}
Plain-string остаётся global (backward compat).

[STAGE1_SEC_V2]
"""
import importlib
import json
import uuid as _uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient


def _mk_project(db, name):
    from app import Project
    p = Project(
        name=name, created_at=datetime.utcnow(), is_deleted=False,
        object_class="pig", object_class_source="list",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return int(p.id)


@pytest.fixture
def v2_ctx(monkeypatch, tmp_path, clean_auth_db):
    """Fresh app + two projects; env API_KEY updatable per-test."""
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "v2_scope.db"))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("CSRF_STRICT", "0")
    monkeypatch.setenv("API_KEY", "placeholder_key")

    import config as _cfg
    importlib.reload(_cfg)
    import app as app_mod
    importlib.reload(app_mod)

    db = app_mod.SessionLocal()
    try:
        sfx = _uuid.uuid4().hex[:6]
        pid1 = _mk_project(db, f"scope_p1_{sfx}")
        pid2 = _mk_project(db, f"scope_p2_{sfx}")
    finally:
        db.close()

    client = TestClient(app_mod.app)
    return client, pid1, pid2


def test_plain_key_grants_global_access(v2_ctx, monkeypatch):
    client, pid1, pid2 = v2_ctx
    monkeypatch.setenv("API_KEY", "secret_global_token")
    headers = {"Authorization": "Bearer secret_global_token"}
    for pid in (pid1, pid2):
        r = client.get(f"/api/v2/projects/{pid}/images", headers=headers)
        assert r.status_code == 200, r.text


def test_scoped_key_allows_listed_project(v2_ctx, monkeypatch):
    client, pid1, _pid2 = v2_ctx
    monkeypatch.setenv(
        "API_KEY", json.dumps({"tokenA": {"projects": [pid1]}})
    )
    headers = {"Authorization": "Bearer tokenA"}
    r = client.get(f"/api/v2/projects/{pid1}/images", headers=headers)
    assert r.status_code == 200, r.text


def test_scoped_key_denies_foreign_project(v2_ctx, monkeypatch):
    client, pid1, pid2 = v2_ctx
    monkeypatch.setenv(
        "API_KEY", json.dumps({"tokenA": {"projects": [pid1]}})
    )
    headers = {"Authorization": "Bearer tokenA"}
    r = client.get(f"/api/v2/projects/{pid2}/images", headers=headers)
    assert r.status_code == 403, r.text
    detail = r.json().get("detail", {})
    assert isinstance(detail, dict), detail
    assert detail.get("key") == "error.forbidden", detail


def test_wildcard_scope_allows_all(v2_ctx, monkeypatch):
    client, pid1, pid2 = v2_ctx
    monkeypatch.setenv(
        "API_KEY", json.dumps({"tokenB": {"projects": "*"}})
    )
    headers = {"Authorization": "Bearer tokenB"}
    for pid in (pid1, pid2):
        r = client.get(f"/api/v2/projects/{pid}/images", headers=headers)
        assert r.status_code == 200, r.text


def test_invalid_bearer_returns_403(v2_ctx, monkeypatch):
    client, pid1, _pid2 = v2_ctx
    monkeypatch.setenv(
        "API_KEY", json.dumps({"tokenA": {"projects": "*"}})
    )
    r = client.get(
        f"/api/v2/projects/{pid1}/images",
        headers={"Authorization": "Bearer not_a_valid_token"},
    )
    assert r.status_code == 403, r.text


def test_list_projects_filtered_by_scope(v2_ctx, monkeypatch):
    client, pid1, pid2 = v2_ctx
    monkeypatch.setenv(
        "API_KEY", json.dumps({"tokenA": {"projects": [pid1]}})
    )
    r = client.get(
        "/api/v2/projects",
        headers={"Authorization": "Bearer tokenA"},
    )
    assert r.status_code == 200, r.text
    ids = [int(p["id"]) for p in r.json()]
    assert pid1 in ids
    assert pid2 not in ids


def test_task_status_denied_for_foreign_project(v2_ctx, monkeypatch):
    """Task создан для pid2, токен ограничен pid1 → 403."""
    client, pid1, pid2 = v2_ctx
    monkeypatch.setenv(
        "API_KEY", json.dumps({"tokenA": {"projects": [pid1]}})
    )
    headers = {"Authorization": "Bearer tokenA"}

    import routers.api_v2 as api_v2_mod
    _tid = "fake_task_scope_test"
    with api_v2_mod._TASKS_LOCK:
        api_v2_mod._TASKS[_tid] = {
            "task_id": _tid,
            "kind": "autolabel",
            "project_id": pid2,
            "status": "done",
            "progress": 100.0,
            "message": "ok",
            "created_ts": 0,
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
        }
    try:
        r = client.get(f"/api/v2/tasks/{_tid}", headers=headers)
        assert r.status_code == 403, r.text
        detail = r.json().get("detail", {})
        assert isinstance(detail, dict) and detail.get("key") == "error.forbidden"
    finally:
        with api_v2_mod._TASKS_LOCK:
            api_v2_mod._TASKS.pop(_tid, None)
