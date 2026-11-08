"""[STAGE4:E4-REDUCED-MOTION] prefersReducedMotion honored."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "js" / "main.js"


def test_render_live_charts_respects_reduced_motion():
    src = MAIN.read_text(encoding="utf-8")
    idx = src.find("function _renderLiveTrainCharts")
    assert idx >= 0
    end = src.find("\nfunction ", idx + 1)
    if end < 0:
        end = len(src)
    body = src[idx:end]
    assert "prefersReducedMotion" in body
    assert "noAnim" in body
