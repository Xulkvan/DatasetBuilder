"""Миграция переносит все таблицы и не тащит secret_key вебхуков."""
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def test_migration_order_covers_all_tables():
    from models import Base
    from services.migrate_service import _MIGRATION_ORDER
    expected = {t.name for t in Base.metadata.sorted_tables}
    assert {name for name, _ in _MIGRATION_ORDER} == expected


def test_copy_table_orm_all_rows_and_webhook_secret_blank(tmp_path):
    from models import (
        Base, Project, User, Webhook,
    )
    from services.migrate_service import (
        _MIGRATION_ORDER, _COPY_OVERRIDES, _copy_table_orm,
    )

    src_engine = create_engine(f"sqlite:///{tmp_path / 'src.db'}")
    dst_engine = create_engine(f"sqlite:///{tmp_path / 'dst.db'}")
    Base.metadata.create_all(bind=src_engine)
    Base.metadata.create_all(bind=dst_engine)
    Src = sessionmaker(bind=src_engine)
    Dst = sessionmaker(bind=dst_engine)

    src = Src()
    p = Project(name="MP", created_at=datetime.utcnow(),
                is_deleted=False, object_class="pig",
                object_class_source="list")
    src.add(p); src.commit(); src.refresh(p)
    src.add(User(username="muser", password_hash="x", role="annotator",
                 is_active=1, created_at=datetime.utcnow()))
    src.add(Webhook(project_id=p.id, url="https://example.com/h",
                    event_type="annotation.saved", secret_key="s3cr3t",
                    active=True, created_at=datetime.utcnow()))
    src.commit()

    model_by_name = {
        "projects": Project, "users": User, "webhooks": Webhook,
    }
    dst = Dst()
    try:
        for tname, _ in _MIGRATION_ORDER:
            cls = model_by_name.get(tname)
            if cls is None:
                continue
            _copy_table_orm(src, dst, cls, tname,
                            overrides=_COPY_OVERRIDES.get(tname))
            dst.commit()
        wh = dst.query(Webhook).one()
        assert wh.secret_key in ("", None)
        assert dst.query(Project).count() == 1
        assert dst.query(User).count() == 1
        violations = dst.execute(text("PRAGMA foreign_key_check")).fetchall()
        assert violations == []
    finally:
        dst.close(); src.close()
