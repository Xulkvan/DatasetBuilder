"""[STAGE2:sdk-client] DatasetBuilderClient."""
from __future__ import annotations

import os
from typing import Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore


class DatasetBuilderClient:
    """Простой Python-клиент для DatasetBuilder API v2."""

    def __init__(self, base_url: str = "http://localhost:8000",
                 api_key: Optional[str] = None):
        if requests is None:
            raise RuntimeError("Install `requests` to use the SDK")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["X-Requested-With"] = "DatasetBuilder"
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def list_projects(self) -> list:
        r = self.session.get(self._url("/api/v2/projects"))
        r.raise_for_status()
        return r.json()

    def upload_images(self, project_id: int, paths: list[str]) -> list:
        """Загрузить изображения в проект. Возвращает список {id, filename,...}."""
        out = []
        for p in paths:
            with open(p, "rb") as f:
                r = self.session.post(
                    self._url(f"/api/projects/{project_id}/images"),
                    files={"file": (os.path.basename(p), f, "image/jpeg")})
            if r.ok:
                out.append(r.json())
            else:
                out.append({"error": r.text, "path": p})
        return out

    def autolabel(self, project_id: int) -> dict:
        """Async autolabel → {'task_id': ..., 'status': 'queued'}"""
        r = self.session.post(
            self._url(f"/api/v2/projects/{project_id}/autolabel"))
        r.raise_for_status()
        return r.json()

    def task_status(self, task_id: str) -> dict:
        r = self.session.get(self._url(f"/api/v2/tasks/{task_id}"))
        r.raise_for_status()
        return r.json()

    def wait_task(self, task_id: str, timeout: float = 600.0,
                  poll_interval: float = 1.5) -> dict:
        import time
        t0 = time.time()
        while time.time() - t0 < timeout:
            st = self.task_status(task_id)
            if st.get("status") in ("done", "error"):
                return st
            time.sleep(poll_interval)
        raise TimeoutError(f"Task {task_id} did not finish in {timeout}s")

    def export_dataset(self, project_id: int, fmt: str = "yolo",
                       naming: str = "numbered", split: str = "none",
                       out_path: Optional[str] = None) -> str:
        url = self._url(f"/api/projects/{project_id}/export/{fmt}")
        params = {"naming": naming, "split": split}
        r = self.session.get(url, params=params, stream=True)
        r.raise_for_status()
        out_path = out_path or f"{fmt}_project_{project_id}.zip"
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return out_path

    def export_parquet(self, project_id: int,
                       out_path: Optional[str] = None) -> str:
        url = self._url(f"/api/projects/{project_id}/export/parquet")
        r = self.session.get(url, stream=True)
        r.raise_for_status()
        out_path = out_path or f"parquet_project_{project_id}.zip"
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return out_path

    def export_sql(self, project_id: int,
                   out_path: Optional[str] = None) -> str:
        url = self._url(f"/api/projects/{project_id}/export/sql")
        r = self.session.get(url, stream=True)
        r.raise_for_status()
        out_path = out_path or f"sql_project_{project_id}.sql"
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return out_path
