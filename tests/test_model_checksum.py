"""Stage 5.3 — model SHA256 verification with local pinning.

Регрессия: без механизма pin'а в models/checksums.json пользователь не
мог защититься от подмены CDN/MITM, даже если модель уже скачивалась
ранее. Первый download — best-effort (pin), повторные — strict (verify).
"""
import json

from services.bootstrap_service import _verify_model_sha256


def test_checksum_first_download_pins(tmp_path, monkeypatch):
    """[STAGE5] Без YOLO_MODEL_SHA256 entry — хэш pin'ится локально."""
    import config
    monkeypatch.setattr(config, "MODEL_DIR", str(tmp_path))
    f = tmp_path / "m1.pt"
    f.write_bytes(b"data1")
    cs_path = tmp_path / "checksums.json"
    if cs_path.exists():
        cs_path.unlink()
    assert _verify_model_sha256(str(f), "first_pin.pt") is True
    assert cs_path.exists(), "checksums.json not created"
    d = json.loads(cs_path.read_text(encoding="utf-8"))
    assert "first_pin.pt" in d


def test_checksum_match(tmp_path, monkeypatch):
    """[STAGE5] Совпадение с YOLO_MODEL_SHA256 → True."""
    import hashlib
    import config
    monkeypatch.setattr(config, "MODEL_DIR", str(tmp_path))
    f = tmp_path / "m2.pt"
    f.write_bytes(b"data_match")
    h = hashlib.sha256(b"data_match").hexdigest()
    monkeypatch.setattr(config, "YOLO_MODEL_SHA256", {"match.pt": h})
    assert _verify_model_sha256(str(f), "match.pt") is True


def test_first_download_pins_checksum(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "MODEL_DIR", str(tmp_path))
    f = tmp_path / "m3.pt"
    f.write_bytes(b"data_pin_test")
    cs_path = tmp_path / "checksums.json"
    if cs_path.exists():
        cs_path.unlink()
    assert _verify_model_sha256(str(f), "pin_test.pt") is True
    assert cs_path.exists()
    d = json.loads(cs_path.read_text(encoding="utf-8"))
    assert "pin_test.pt" in d


def test_second_download_matches_pinned(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "MODEL_DIR", str(tmp_path))
    f = tmp_path / "m4.pt"
    f.write_bytes(b"data_second")
    # First call — pins
    assert _verify_model_sha256(str(f), "second.pt") is True
    # Second call — matches pinned
    assert _verify_model_sha256(str(f), "second.pt") is True


def test_tampered_file_rejected(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "MODEL_DIR", str(tmp_path))
    f = tmp_path / "m5.pt"
    f.write_bytes(b"original_data")
    # First call — pins
    assert _verify_model_sha256(str(f), "tamper.pt") is True
    # Tamper
    f.write_bytes(b"tampered_data")
    assert _verify_model_sha256(str(f), "tamper.pt") is False
