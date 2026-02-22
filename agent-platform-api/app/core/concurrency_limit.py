import logging

import redis.asyncio as aioredis

from agent_core.settings import get_settings


_LOGGER = logging.getLogger(__name__)


def _redis():
    settings = get_settings()
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def acquire_concurrency(key: str, limit: int, ttl_sec: int = 1800) -> tuple[bool, int]:
    redis = _redis()
    redis_key = f"apicc:{key}"
    try:
        count = await redis.incr(redis_key)
        if count == 1:
            await redis.expire(redis_key, ttl_sec)
        else:
            await redis.expire(redis_key, ttl_sec)
        if count > max(1, int(limit)):
            await redis.decr(redis_key)
            return False, int(limit)
        return True, count
    except Exception as exc:
        _LOGGER.error("Concurrency acquire error: %s", exc)
        return True, 0
    finally:
        try:
            await redis.close()
        except Exception:
            pass


async def release_concurrency(key: str) -> None:
    redis = _redis()
    redis_key = f"apicc:{key}"
    try:
        cur = await redis.get(redis_key)
        if cur is None:
            return
        if int(cur) <= 1:
            await redis.delete(redis_key)
        else:
            await redis.decr(redis_key)
    except Exception as exc:
        _LOGGER.error("Concurrency release error: %s", exc)
    finally:
        try:
            await redis.close()
        except Exception:
            pass
