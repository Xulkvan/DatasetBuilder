"""[STAGE6] export_sql_dump экранирует \\ и ' в именах файлов."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import (
    app, SessionLocal,
    Project, ImageModel, Annotation,
)

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def test_backslash_and_quote_escaped():
    db = SessionLocal()
    try:
        p = Project(name="sql_esc", created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p)
        db.commit()
        db.refresh(p)
        pid = p.id
        im = ImageModel(project_id=pid,
                        filename="weird\\name'o.jpg",
                        path="/tmp/_x.jpg", width=640, height=640,
                        is_deleted=False)
        db.add(im)
        db.commit()
        db.refresh(im)
        db.add(Annotation(image_id=im.id, x=0.1, y=0.1,
                          w=0.2, h=0.2, label="pig"))
        db.commit()
    finally:
        db.close()

    r = client.get(f"/api/projects/{pid}/export/sql")
    assert r.status_code == 200, r.text
    body = r.text
    # После фикса: "\\" -> "\\\\" и "'" -> "''"
    assert "weird\\\\name''o.jpg" in body, body[:500]
    # Одиночного "\\" перед буквой быть не должно
    assert "weird\\name" not in body
