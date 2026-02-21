import asyncio
import time
from collections import deque

from app.core.config import get_settings


def _parse_limit(limit_expr: str) -> tuple[int, int]:
    raw = (limit_expr or "5/min").strip().lower()
    if "/" not in raw:
        return 5, 60
    amount_s, unit = raw.split("/", 1)
    try:
        amount = max(1, int(amount_s))
    except Exception:
        amount = 5
    unit = unit.strip()
    if unit in ("s", "sec", "second", "seconds"):
        window = 1
    elif unit in ("m", "min", "minute", "minutes"):
        window = 60
    elif unit in ("h", "hour", "hours"):
        window = 3600
    else:
        window = 60
    return amount, window


class InMemoryRateLimiter:
    def __init__(self):
        self._buckets: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def check_and_consume(self, key: str, limit_expr: str) -> tuple[bool, int]:
        limit, window_sec = _parse_limit(limit_expr)
        now = time.time()
        async with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            cutoff = now - window_sec
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, int(window_sec - (now - bucket[0])))
                return False, retry_after

            bucket.append(now)
            return True, 0


_rate_limiter = InMemoryRateLimiter()


async def consume_login_failure(key: str) -> tuple[bool, int]:
    settings = get_settings()
    return await _rate_limiter.check_and_consume(key, settings.auth_rate_limit_login)


async def clear_login_failures(key: str) -> None:
    async with _rate_limiter._lock:
        _rate_limiter._buckets.pop(key, None)
