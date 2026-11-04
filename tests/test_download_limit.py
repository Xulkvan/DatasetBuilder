"""[STAGE-2-PATCH-V3] Download size limits (1.5, 1.6).

Покрывает:
  * _download_to_file: max_bytes enforcement (Content-Length + streaming)
  * _coco_to_zip: per-image max_bytes (oversized -> missing)
  * _coco_to_zip: SSRF-blocked URL -> missing
"""
import pytest
from fastapi import HTTPException


def _allow_any_url(monkeypatch):
    """Bypass SSRF check (тестируем лимит размера, а не SSRF)."""
    import app as app_mod
    monkeypatch.setattr(app_mod, "is_safe_external_url", lambda url: True)


def _install_fake_urlopen(monkeypatch, *, content_length=None, data_chunks=None):
    import urllib.request
    chunks = list(data_chunks or [])

    class FakeResp:
        def __init__(self):
            self.headers = {}
            if content_length is not None:
                self.headers["Content-Length"] = str(content_length)
            self._chunks = list(chunks)

        def read(self, n):
            if not self._chunks:
                return b""
            return self._chunks.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        return FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


# ===========================================================================
# _download_to_file (1.5)
# ===========================================================================

def test_content_length_exceeded(monkeypatch, tmp_path):
    from app import _download_to_file
    _allow_any_url(monkeypatch)
    _install_fake_urlopen(
        monkeypatch, content_length=1_000_000, data_chunks=[b"x" * 100],
    )

    dest = tmp_path / "out.bin"
    with pytest.raises(HTTPException) as ei:
        _download_to_file("http://example.com/x", str(dest), max_bytes=100)
    assert ei.value.status_code == 413


def test_streaming_exceeds_limit(monkeypatch, tmp_path):
    from app import _download_to_file
    _allow_any_url(monkeypatch)
    _install_fake_urlopen(
        monkeypatch, content_length=None,
        data_chunks=[b"x" * 1024] * 20,
    )

    dest = tmp_path / "out.bin"
    with pytest.raises(HTTPException) as ei:
        _download_to_file("http://example.com/x", str(dest), max_bytes=1024)
    assert ei.value.status_code == 413


def test_download_within_limit(monkeypatch, tmp_path):
    from app import _download_to_file
    _allow_any_url(monkeypatch)
    _install_fake_urlopen(
        monkeypatch, content_length=100, data_chunks=[b"x" * 100],
    )

    dest = tmp_path / "ok.bin"
    _download_to_file("http://example.com/x", str(dest), max_bytes=1024)
    assert dest.read_bytes() == b"x" * 100


# ===========================================================================
# _coco_to_zip (1.6)
# ===========================================================================

def test_coco_to_zip_oversized_image_goes_to_missing(monkeypatch, tmp_path):
    from app import _coco_to_zip
    _allow_any_url(monkeypatch)
    _install_fake_urlopen(
        monkeypatch, content_length=10000, data_chunks=[b"x" * 100],
    )

    coco = {
        "images": [{"id": 1, "file_name": "a.jpg",
                    "width": 100, "height": 100}],
        "annotations": [],
        "categories": [],
    }
    image_urls = {"a.jpg": "http://example.com/a.jpg"}
    out_path = tmp_path / "out.zip"
    r = _coco_to_zip(coco, image_urls, str(out_path), max_per_image=1024)
    assert r["downloaded"] == 0
    assert "a.jpg" in r["missing"]


def test_coco_to_zip_ssrf_blocked(monkeypatch, tmp_path):
    """Unsafe URL -> missing (SSRF protection)."""
    import app as app_mod
    monkeypatch.setattr(app_mod, "is_safe_external_url", lambda url: False)
    from app import _coco_to_zip

    coco = {
        "images": [{"id": 1, "file_name": "a.jpg",
                    "width": 100, "height": 100}],
        "annotations": [],
        "categories": [],
    }
    image_urls = {"a.jpg": "http://127.0.0.1/a.jpg"}
    out_path = tmp_path / "out.zip"
    r = _coco_to_zip(coco, image_urls, str(out_path))
    assert r["downloaded"] == 0
    assert "a.jpg" in r["missing"]
