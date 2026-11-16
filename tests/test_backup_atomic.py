"""create_backup: уникальные имена, атомарная запись через tempfile."""
import os
import zipfile
from datetime import datetime


def _seed_project():
    from app import SessionLocal
    from models import Project, ImageModel
    db = SessionLocal()
    try:
        p = Project(name="BackupP", created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        db.add(ImageModel(project_id=p.id, filename="b.jpg",
                          path="/tmp/_b.jpg", width=640, height=640,
                          is_deleted=False, created_at=datetime.utcnow()))
        db.commit()
        return p.id
    finally:
        db.close()


def test_backup_names_unique_and_zip_valid(local_app_client):
    import config
    from app import SessionLocal
    from services.backup_service import create_backup

    pid = _seed_project()
    db = SessionLocal()
    try:
        p1, _ = create_backup(db, pid, prefix="backup_project")
        p2, _ = create_backup(db, pid, prefix="backup_project")
    finally:
        db.close()

    assert p1 != p2
    assert os.path.exists(p1) and os.path.exists(p2)
    for path in (p1, p2):
        assert zipfile.is_zipfile(path)
        base = os.path.basename(path)
        assert base.startswith(f"backup_project_{pid}_")
        assert base.endswith(".zip")
    leftovers = [n for n in os.listdir(config.BACKUP_DIR)
                 if n.endswith(".part")]
    assert not leftovers
