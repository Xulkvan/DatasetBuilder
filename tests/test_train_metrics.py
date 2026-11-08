"""Regression: /api/train/runs/{folder}/metrics возвращает metadata+epochs.

До QUALITY-F3-TRAIN-METRICS эндпоинт был заглушкой
({"metadata": None, "epochs": []}), из-за чего модалка «Метрики»
и сравнение моделей открывались пустыми.
"""
import json
import os
import shutil
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import app
from config import RUNS_DIR

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


@pytest.fixture
def fake_run(tmp_path):
    """Создает временный run в RUNS_DIR и удаляет после теста."""
    folder = "train_20990101_000000"
    run_dir = os.path.join(RUNS_DIR, folder)
    os.makedirs(os.path.join(run_dir, "output", "train"), exist_ok=True)

    meta = {
        "run_id": "20990101_000000",
        "created_at": datetime.utcnow().isoformat(),
        "project_id": 1,
        "object_class": "pig",
        "model_name": "pig_v1.pt",
        "epochs": 2,
        "imgsz": 640,
        "annotated_count": 10,
        "summary": {"best_epoch": 2, "mAP50": 0.85, "mAP50_95": 0.60},
    }
    with open(os.path.join(run_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)

    with open(os.path.join(run_dir, "output", "train", "results.csv"), "w",
              encoding="utf-8") as f:
        f.write("epoch,metrics/mAP50(B),metrics/mAP50-95(B),"
                "train/box_loss,val/box_loss\n")
        f.write("1,0.80,0.55,1.2,1.1\n")
        f.write("2,0.85,0.60,0.9,0.8\n")

    yield folder

    shutil.rmtree(run_dir, ignore_errors=True)


class TestTrainMetrics:
    def test_returns_metadata_and_epochs(self, fake_run):
        r = client.get(f"/api/train/runs/{fake_run}/metrics")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["folder"] == fake_run
        assert d["metadata"] is not None, (
            "metadata должен быть не-None для прогона с metadata.json"
        )
        assert d["metadata"]["run_id"] == "20990101_000000"
        assert d["metadata"]["model_name"] == "pig_v1.pt"
        assert len(d["epochs"]) == 2
        assert d["epochs"][1]["epoch"] == 2
        assert d["epochs"][1]["mAP50"] == pytest.approx(0.85)

    def test_missing_run_returns_404(self):
        r = client.get("/api/train/runs/train_does_not_exist_xyz/metrics")
        assert r.status_code == 404

    def test_invalid_folder_returns_400(self):
        r = client.get("/api/train/runs/not_a_train_folder/metrics")
        assert r.status_code == 400

    def test_path_traversal_rejected(self):
        # _is_simple_filename отсекает .. и /
        r = client.get("/api/train/runs/train_../etc/metrics")
        assert r.status_code in (400, 404)

    def test_run_without_metadata_json(self, tmp_path):
        """Старые прогоны без metadata.json - metadata=None, не 500."""
        folder = "train_20990101_000001"
        run_dir = os.path.join(RUNS_DIR, folder)
        os.makedirs(os.path.join(run_dir, "output", "train"), exist_ok=True)
        try:
            with open(os.path.join(run_dir, "output", "train", "results.csv"),
                      "w", encoding="utf-8") as f:
                f.write("epoch,metrics/mAP50(B)\n1,0.5\n")
            r = client.get(f"/api/train/runs/{folder}/metrics")
            assert r.status_code == 200
            d = r.json()
            assert d["metadata"] is None
            assert len(d["epochs"]) == 1
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
