import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import deque

import redis.asyncio as aioredis

from agent_core.settings import get_settings


_LOGGER = logging.getLogger(__name__)


def parse_limit(limit_expr: str) -> tuple[int, int]:
    raw = (limit_expr or "60/min").strip().lower()
    if "/" not in raw:
        return 60, 60
    amount_s, unit = raw.split("/", 1)
    try:
        amount = max(1, int(amount_s))
    except Exception:
        amount = 60
    unit = unit.strip()
    if unit in ("s", "sec", "second", "seconds"):
        window = 1
    elif unit in ("h", "hour", "hours"):
        window = 3600
    else:
        window = 60
    return amount, window


class RateLimiterBackend(ABC):
    @abstractmethod
    async def check_and_consume(self, key: str, limit_expr: str) -> tuple[bool, int]:
        raise NotImplementedError


class InMemoryRateLimiterBackend(RateLimiterBackend):
    def __init__(self):
        self._buckets: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def check_and_consume(self, key: str, limit_expr: str) -> tuple[bool, int]:
        limit, window_sec = parse_limit(limit_expr)
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


class RedisRateLimiterBackend(RateLimiterBackend):
    def __init__(self, redis_url: str):
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def check_and_consume(self, key: str, limit_expr: str) -> tuple[bool, int]:
        limit, window_sec = parse_limit(limit_expr)
        redis_key = f"apirl:{key}"
        count = await self._redis.incr(redis_key)
        if count == 1:
            await self._redis.expire(redis_key, window_sec)
        if count > limit:
            ttl = await self._redis.ttl(redis_key)
            retry_after = max(1, int(ttl if ttl and ttl > 0 else window_sec))
            return False, retry_after
        return True, 0


_backend: RateLimiterBackend | None = None


def _fail_mode_open() -> bool:
    settings = get_settings()
    return (settings.rate_limit_fail_mode or "open").strip().lower() == "open"


def get_rate_limiter_backend() -> RateLimiterBackend:
    global _backend
    if _backend is not None:
        return _backend
    settings = get_settings()
    mode = (settings.rate_limit_backend or "redis").strip().lower()
    if mode == "memory":
        _backend = InMemoryRateLimiterBackend()
    else:
        _backend = RedisRateLimiterBackend(settings.redis_url)
    return _backend


async def consume_or_allow(key: str, limit_expr: str) -> tuple[bool, int]:
    backend = get_rate_limiter_backend()
    try:
        return await backend.check_and_consume(key, limit_expr)
    except Exception as exc:
        _LOGGER.error("Rate limiter backend error: %s", exc)
        if _fail_mode_open():
            return True, 0
        return False, 1
