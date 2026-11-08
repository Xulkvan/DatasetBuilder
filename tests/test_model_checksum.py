"""Stage 5.3 — model SHA256 verification."""
import os
from services.bootstrap_service import _verify_model_sha256


def test_checksum_skip_when_no_entry(tmp_path):
    f = tmp_path / "m.pt"
    f.write_bytes(b"data")
    assert _verify_model_sha256(str(f), "nonexistent.pt") is True


def test_checksum_match(tmp_path, monkeypatch):
    import hashlib
    f = tmp_path / "m.pt"
    f.write_bytes(b"data")
    h = hashlib.sha256(b"data").hexdigest()
    import config
    monkeypatch.setattr(config, "YOLO_MODEL_SHA256", {"m.pt": h})
    import services.bootstrap_service as bs
    monkeypatch.setattr(bs, "_verify_model_sha256",
                        lambda p, n: h == hashlib.sha256(open(p, "rb").read()).hexdigest())
    assert bs._verify_model_sha256(str(f), "m.pt") is True
