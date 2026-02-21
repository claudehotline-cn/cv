import pytest

from app.core.rate_limit import InMemoryRateLimiterBackend, _parse_limit


def test_parse_limit_defaults():
    assert _parse_limit("invalid") == (5, 60)


def test_parse_limit_minutes():
    assert _parse_limit("10/min") == (10, 60)


@pytest.mark.asyncio
async def test_inmemory_backend_limit_and_clear():
    backend = InMemoryRateLimiterBackend()
    key = "login:test@example.com:127.0.0.1"

    ok1, _ = await backend.check_and_consume(key, "2/min")
    ok2, _ = await backend.check_and_consume(key, "2/min")
    ok3, retry = await backend.check_and_consume(key, "2/min")

    assert ok1 is True
    assert ok2 is True
    assert ok3 is False
    assert retry >= 1

    await backend.clear(key)
    ok4, _ = await backend.check_and_consume(key, "2/min")
    assert ok4 is True
