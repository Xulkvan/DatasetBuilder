"""train_start проверяет доступ к проекту до запуска обучения."""


def test_foreign_project_training_forbidden(ann_client):
    client, _ann_id, p1, _p2 = ann_client
    r = client.post("/api/train/start", data={"project_id": str(p1)})
    assert r.status_code == 403, r.text
