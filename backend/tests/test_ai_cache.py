import pytest

from app.ai import cache
from app.config import settings


def test_second_call_is_served_from_cache(conn):
    calls = []

    def call():
        calls.append(1)
        return {"text": "Warmed the palette"}

    inputs = {"a": "sha-a", "b": "sha-b"}
    assert cache.cached(conn, "muse-spark-1.3", inputs, call) == {"text": "Warmed the palette"}
    assert cache.cached(conn, "muse-spark-1.3", inputs, call) == {"text": "Warmed the palette"}
    assert len(calls) == 1


def test_key_ignores_dict_order_but_not_model():
    assert cache.cache_key("m", {"a": 1, "b": 2}) == cache.cache_key("m", {"b": 2, "a": 1})
    assert cache.cache_key("m", {"a": 1}) != cache.cache_key("n", {"a": 1})


def test_offline_mode_never_calls(conn, monkeypatch):
    monkeypatch.setattr(settings, "ai_offline", True)
    with pytest.raises(cache.AIOffline):
        cache.cached(conn, "sam-3.1", {"blob": "x"}, lambda: pytest.fail("model was called"))
