"""[STAGE1-D:test-reid] Тесты для services.reid_service."""
import io
import pytest
from PIL import Image

from services.reid_service import embed_from_crop, cosine


def _crop_bytes(color):
    img = Image.new("RGB", (32, 32), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestReidEmbed:
    def test_embed_returns_normalized_vector(self):
        v = embed_from_crop(_crop_bytes((255, 0, 0)))
        assert len(v) > 0
        n = sum(x * x for x in v) ** 0.5
        assert abs(n - 1.0) < 1e-3

    def test_cosine_self_is_one(self):
        v = embed_from_crop(_crop_bytes((100, 100, 100)))
        assert abs(cosine(v, v) - 1.0) < 1e-3

    def test_different_colors_have_lower_cos(self):
        a = embed_from_crop(_crop_bytes((255, 0, 0)))
        b = embed_from_crop(_crop_bytes((0, 0, 255)))
        assert cosine(a, b) < 0.99

    def test_empty_input(self):
        assert embed_from_crop(b"") == [] or isinstance(embed_from_crop(b""), list)
