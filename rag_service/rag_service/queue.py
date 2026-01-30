"""Background job queue helpers (ARQ)."""

from __future__ import annotations

from typing import Any, Optional


async def enqueue_job(function: str, *args: Any, job_id: Optional[str] = None, **kwargs: Any) -> str:
    """Enqueue an ARQ job and return job_id."""
    from arq import create_pool
    from arq.connections import RedisSettings

    from .config import settings

    redis_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        job = await redis_pool.enqueue_job(
            function,
            *args,
            _job_id=job_id,
            _queue_name=settings.queue_name,
            **kwargs,
        )
        return job.job_id
    finally:
        await redis_pool.close()
