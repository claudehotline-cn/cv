from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException

from agent_core.settings import get_settings

from .concurrency_limit import acquire_concurrency, release_concurrency
from .rate_limit import consume_or_allow


Bucket = Literal["read", "write", "execute"]


@dataclass
class GovernanceKeys:
    tenant_id: str
    user_id: str


def _tenant_limit_expr(bucket: Bucket) -> str:
    settings = get_settings()
    if bucket == "read":
        return settings.rate_limit_tenant_read
    if bucket == "write":
        return settings.rate_limit_tenant_write
    return settings.rate_limit_tenant_execute


def _user_limit_expr(bucket: Bucket) -> str:
    settings = get_settings()
    if bucket == "read":
        return settings.rate_limit_user_read
    if bucket == "write":
        return settings.rate_limit_user_write
    return settings.rate_limit_user_execute


async def enforce_rate_limit(keys: GovernanceKeys, bucket: Bucket) -> None:
    tenant_key = f"tenant:{keys.tenant_id}:{bucket}"
    user_key = f"user:{keys.tenant_id}:{keys.user_id}:{bucket}"

    ok_tenant, retry_tenant = await consume_or_allow(tenant_key, _tenant_limit_expr(bucket))
    if not ok_tenant:
        raise HTTPException(
            status_code=429,
            detail={
                "detail": "rate_limit_exceeded",
                "scope": "tenant",
                "bucket": bucket,
                "retry_after": retry_tenant,
            },
        )

    ok_user, retry_user = await consume_or_allow(user_key, _user_limit_expr(bucket))
    if not ok_user:
        raise HTTPException(
            status_code=429,
            detail={
                "detail": "rate_limit_exceeded",
                "scope": "user",
                "bucket": bucket,
                "retry_after": retry_user,
            },
        )


async def acquire_execute_concurrency(keys: GovernanceKeys) -> tuple[bool, str]:
    settings = get_settings()
    tenant_key = f"tenant:{keys.tenant_id}:execute"
    user_key = f"user:{keys.tenant_id}:{keys.user_id}:execute"

    ok_tenant, _ = await acquire_concurrency(tenant_key, settings.concurrency_limit_tenant_execute)
    if not ok_tenant:
        return False, "tenant"

    ok_user, _ = await acquire_concurrency(user_key, settings.concurrency_limit_user_execute)
    if not ok_user:
        await release_concurrency(tenant_key)
        return False, "user"

    return True, ""


async def release_execute_concurrency(keys: GovernanceKeys) -> None:
    await release_concurrency(f"tenant:{keys.tenant_id}:execute")
    await release_concurrency(f"user:{keys.tenant_id}:{keys.user_id}:execute")
