"""[STAGE6-T11] _scale_to_coco не падает на int id."""
from app import _scale_to_coco


def test_scale_int_reference_id():
    items = [{
        "id": 42,
        "reference_id": 42,      # int, не str
        "width": 100, "height": 100,
        "annotations": [
            {"label": "pig",
             "geometry": {"x": 10, "y": 10, "width": 20, "height": 20}},
        ],
    }]
    coco = _scale_to_coco(items)
    assert len(coco["images"]) == 1
    assert isinstance(coco["images"][0]["file_name"], str), \
        f"file_name должен быть str, получен {type(coco['images'][0]['file_name'])}"


def test_scale_string_reference_id():
    items = [{
        "id": "abc",
        "reference_id": "abc",
        "width": 100, "height": 100,
        "annotations": [],
    }]
    coco = _scale_to_coco(items)
    assert coco["images"][0]["file_name"] == "abc"


def test_scale_empty_annotations():
    items = [{
        "id": 7,
        "width": 100, "height": 100,
        "annotations": [],
    }]
    coco = _scale_to_coco(items)
    assert len(coco["images"]) == 1
    assert len(coco["annotations"]) == 0
