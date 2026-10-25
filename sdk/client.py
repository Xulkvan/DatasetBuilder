"""[STAGE1:sdk-async] Async DatasetBuilder SDK on httpx."""
from __future__ import annotations

import asyncio
import os
from typing import Optional


try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


class AsyncDatasetBuilderClient:
    """Асинхронный клиент DatasetBuilder API v2.

    Пример:
        async with AsyncDatasetBuilderClient(api_key="...") as c:
            projects = await c.list_projects()
            results = await c.upload_batch(projects[0]["id"], ["a.jpg", "b.jpg"])
            coco = await c.get_dataset_coco(projects[0]["id"])
    """

    def __init__(self, base_url: str = "http://localhost:8000",
                 api_key: Optional[str] = None,
                 timeout: float = 120.0) -> None:
        if httpx is None:
            raise RuntimeError(
                "Install `httpx` to use the SDK: pip install httpx"
            )
        self.base_url = base_url.rstrip("/")
        headers = {"X-Requested-With": "DatasetBuilder"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
        )

    async def __aenter__(self) -> "AsyncDatasetBuilderClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_projects(self) -> list:
        r = await self._client.get("/api/v2/projects")
        r.raise_for_status()
        return r.json()

    async def upload_batch(self, project_id: int,
                           file_paths: list[str]) -> list:
        """Параллельная загрузка файлов через asyncio.gather."""
        async def _one(p: str):
            fname = os.path.basename(p)
            try:
                with open(p, "rb") as f:
                    files = {"file": (fname, f, "image/jpeg")}
                    r = await self._client.post(
                        f"/api/v2/projects/{project_id}/images",
                        files=files,
                    )
                if r.status_code >= 400:
                    return {"error": r.text, "path": p,
                            "status": r.status_code}
                return r.json()
            except Exception as e:
                return {"error": str(e), "path": p}
        return await asyncio.gather(*[_one(p) for p in file_paths])

    async def get_dataset_coco(self, project_id: int) -> dict:
        r = await self._client.get(
            f"/api/v2/projects/{project_id}/annotations")
        r.raise_for_status()
        return r.json()

    async def start_training(self, project_id: int,
                             config: dict) -> dict:
        r = await self._client.post(
            f"/api/v2/projects/{project_id}/train",
            json=config or {},
        )
        r.raise_for_status()
        return r.json()

    async def task_status(self, task_id: str) -> dict:
        r = await self._client.get(f"/api/v2/tasks/{task_id}")
        r.raise_for_status()
        return r.json()

    async def export_dataset(self, project_id: int,
                             fmt: str = "yolo") -> dict:
        r = await self._client.post(
            f"/api/v2/projects/{project_id}/export/{fmt}")
        r.raise_for_status()
        return r.json()
