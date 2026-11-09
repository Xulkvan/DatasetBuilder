"""[STAGE6] YOLO batch inference: один model() call для list(img_paths).

Проверяет:
  * батч-вызов используется (model(list));
  * fallback на per-image при ошибке батча;
  * корректная распаковка результатов и фильтрация по классам.
"""
from types import SimpleNamespace


def _fake_box(cls_id, conf, xyxy):
    return SimpleNamespace(
        cls=[cls_id],
        conf=[conf],
        xyxy=[SimpleNamespace(tolist=lambda: list(xyxy))],
    )


class _FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class _FakeYOLO:
    """Фейк: model(list) -> list[list[Results]], model(path) -> list[Results]."""

    def __init__(self, boxes_per_path=None, fail_batch=False):
        self.boxes_per_path = boxes_per_path or {}
        self.fail_batch = fail_batch
        self.batch_calls = 0
        self.per_image_calls = 0

    def __call__(self, source, **kwargs):
        if isinstance(source, list):
            self.batch_calls += 1
            if self.fail_batch:
                raise RuntimeError("batch failed")
            out = []
            for path in source:
                boxes = self.boxes_per_path.get(path, [])
                out.append([_FakeResult(boxes)])
            return out
        self.per_image_calls += 1
        boxes = self.boxes_per_path.get(source, [])
        return [_FakeResult(boxes)]


def test_batch_predict_uses_single_call():
    from services.ml_service import _autolabel_batch_predict
    paths = ["/tmp/a.jpg", "/tmp/b.jpg", "/tmp/c.jpg"]
    boxes = {
        "/tmp/a.jpg": [_fake_box(0, 0.9, [10, 10, 50, 50])],
        "/tmp/b.jpg": [],
        "/tmp/c.jpg": [_fake_box(0, 0.7, [100, 100, 200, 200])],
    }
    model = _FakeYOLO(boxes_per_path=boxes)
    result = _autolabel_batch_predict(
        paths, model, [640, 640, 640], [640, 640, 640],
        {0}, "pig",
    )
    assert model.batch_calls == 1, (
        f"expected 1 batch call, got {model.batch_calls}")
    assert model.per_image_calls == 0
    assert len(result) == 3
    assert len(result[0]) == 1
    assert len(result[1]) == 0
    assert len(result[2]) == 1
    assert result[0][0]["label"] == "pig"


def test_batch_predict_fallback_on_error():
    from services.ml_service import _autolabel_batch_predict
    paths = ["/tmp/a.jpg", "/tmp/b.jpg"]
    boxes = {
        "/tmp/a.jpg": [_fake_box(0, 0.9, [10, 10, 50, 50])],
        "/tmp/b.jpg": [_fake_box(0, 0.8, [20, 20, 60, 60])],
    }
    model = _FakeYOLO(boxes_per_path=boxes, fail_batch=True)
    result = _autolabel_batch_predict(
        paths, model, [640, 640], [640, 640], {0}, "pig",
    )
    assert model.batch_calls == 1
    assert model.per_image_calls == 2
    assert len(result) == 2
    assert len(result[0]) == 1
    assert len(result[1]) == 1


def test_batch_predict_filters_by_class():
    from services.ml_service import _autolabel_batch_predict
    paths = ["/tmp/a.jpg"]
    boxes = {"/tmp/a.jpg": [
        _fake_box(0, 0.9, [10, 10, 50, 50]),
        _fake_box(5, 0.9, [100, 100, 200, 200]),
    ]}
    model = _FakeYOLO(boxes_per_path=boxes)
    result = _autolabel_batch_predict(
        paths, model, [640], [640], {0}, "pig",
    )
    assert len(result[0]) == 1
    assert result[0][0]["label"] == "pig"
