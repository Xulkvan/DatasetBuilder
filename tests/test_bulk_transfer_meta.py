"""[STAGE6-T3] bulk_copy сохраняет метаданные изображения."""
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import (
    app, SessionLocal, UPLOAD_DIR,
    Project, ImageModel, Annotation,
)

client = TestClient(app, headers={"X-Requested-With": "DatasetBuilder"})


def _mk_real_file():
    p = Path(UPLOAD_DIR) / ("test_" + uuid.uuid4().hex[:8] + ".jpg")
    Image.new("RGB", (64, 64), (128, 128, 128)).save(p, format="JPEG")
    return str(p)


def _mk_project(name):
    db = SessionLocal()
    try:
        p = Project(name=name, created_at=datetime.utcnow(),
                    is_deleted=False, object_class="pig",
                    object_class_source="list")
        db.add(p); db.commit(); db.refresh(p)
        return p.id
    finally:
        db.close()


def _mk_image(pid, **kw):
    path = _mk_real_file()
    db = SessionLocal()
    try:
        im = ImageModel(
            project_id=pid,
            filename=kw.get("filename") or ("img_" + uuid.uuid4().hex[:6] + ".jpg"),
            path=path,
            width=640, height=640, is_deleted=False,
            original_width=kw.get("original_width"),
            original_height=kw.get("original_height"),
            timestamp_sec=kw.get("timestamp_sec"),
        )
        db.add(im); db.commit(); db.refresh(im)
        return im.id
    finally:
        db.close()


class TestBulkCopyMeta:
    def test_copy_preserves_original_dims(self):
        src_pid = _mk_project("t3_src_dims")
        dst_pid = _mk_project("t3_dst_dims")
        src = _mk_image(src_pid, filename="x.jpg",
                        original_width=1920, original_height=1080,
                        timestamp_sec=12.5)

        r = client.post("/api/images/bulk_copy_to_project", json={
            "image_ids": [src], "target_project_id": dst_pid,
        })
        assert r.status_code == 200, r.text

        db = SessionLocal()
        try:
            dst_imgs = db.query(ImageModel).filter(
                ImageModel.project_id == dst_pid).all()
            assert len(dst_imgs) == 1
            d = dst_imgs[0]
            assert d.original_width == 1920, \
                f"original_width lost: {d.original_width}"
            assert d.original_height == 1080, \
                f"original_height lost: {d.original_height}"
            assert abs((d.timestamp_sec or 0) - 12.5) < 1e-6, \
                f"timestamp_sec lost: {d.timestamp_sec}"
        finally:
            db.close()
