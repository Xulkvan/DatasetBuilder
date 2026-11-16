"""Annotator не может скачивать/создавать бэкап чужого проекта."""


def test_foreign_backup_download_forbidden(ann_client):
    client, _ann_id, p1, _p2 = ann_client
    name = f"backup_project_{p1}_x_20260101_000000_abcdef.zip"
    r = client.get(f"/api/projects/{p1}/backup/download/{name}")
    assert r.status_code == 403, r.text


def test_foreign_backup_create_forbidden(ann_client):
    client, _ann_id, p1, _p2 = ann_client
    assert client.post(f"/api/projects/{p1}/backup").status_code == 403
