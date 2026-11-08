"""Stage 5.9 — api_error helper present and used in api_v2."""
import inspect


def test_api_error_helper_exists():
    from services.errors import api_error
    assert callable(api_error)
    exc = api_error(400, "error.test", "test fallback", x=1)
    assert exc.status_code == 400
    assert exc.detail["key"] == "error.test"
    assert exc.detail["fallback"] == "test fallback"
    assert exc.detail["params"] == {"x": 1}


def test_api_v2_uses_api_error():
    import routers.api_v2 as m
    src = inspect.getsource(m)
    # api_v2 должен использовать helper
    assert "api_error" in src, "api_v2.py не использует api_error"
