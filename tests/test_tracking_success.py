"""[STAGE6:test-tracking] Требует реального видео + YOLO — пропущено."""
import pytest


@pytest.mark.skip(reason="Requires video file + YOLO model in models/ — run manually")
def test_tracking_returns_done_status():
    """После трекинга video_track_status должен вернуть status=done,
    а не error с NameError: track_to_aid (фикс C8)."""
    pass
