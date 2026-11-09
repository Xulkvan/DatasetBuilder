"""[STAGE-2-PATCH-V3] Download size limits (1.5, 1.6).

[STAGE9_DNS_PINNING] urllib.request.urlopen больше не используется —
_download_to_file теперь ходит через services.safe_http_client.get_safe_client.
Мокаем get_safe_client (а не urllib) через httpx.MockTransport.
"""
import httpx
import pytest
from fastapi import HTTPException


def _install_fake_client(monkeypatch, *, content_length=None, data_chunks=None):
    chunks = list(data_chunks or [])
    body = b"".join(chunks)

    def handler(request):
        headers = {}
        if content_length is not None:
            headers["Content-Length"] = str(content_length)
        return httpx.Response(200, headers=headers, content=body)

    import services.safe_http_client as shc

    def _fake_get_safe_client(timeout: float = 30.0):
        return httpx.Client(
            transport=httpx.MockTransport(handler),
            timeout=timeout,
        )

    monkeypatch.setattr(shc, "get_safe_client", _fake_get_safe_client)


def test_content_length_exceeded(monkeypatch, tmp_path):
    from app import _download_to_file
    _install_fake_client(
        monkeypatch, content_length=1_000_000, data_chunks=[b"x" * 100],
    )

    dest = tmp_path / "out.bin"
    with pytest.raises(HTTPException) as ei:
        _download_to_file("http://example.com/x", str(dest), max_bytes=100)
    assert ei.value.status_code == 413


def test_streaming_exceeds_limit(monkeypatch, tmp_path):
    from app import _download_to_file
    _install_fake_client(
        monkeypatch, content_length=None,
        data_chunks=[b"x" * 1024] * 20,
    )

    dest = tmp_path / "out.bin"
    with pytest.raises(HTTPException) as ei:
        _download_to_file("http://example.com/x", str(dest), max_bytes=1024)
    assert ei.value.status_code == 413


def test_download_within_limit(monkeypatch, tmp_path):
    from app import _download_to_file
    _install_fake_client(
        monkeypatch, content_length=100, data_chunks=[b"x" * 100],
    )

    dest = tmp_path / "ok.bin"
    _download_to_file("http://example.com/x", str(dest), max_bytes=1024)
    assert dest.read_bytes() == b"x" * 100


def test_coco_to_zip_oversized_image_goes_to_missing(monkeypatch, tmp_path):
    from app import _coco_to_zip
    _install_fake_client(
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
