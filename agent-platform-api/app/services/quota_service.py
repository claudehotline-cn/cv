from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.settings import get_settings

from ..models.db_models import (
    TenantQuotaPolicyModel,
    TenantQuotaUsageModel,
    TenantRateLimitPolicyModel,
)


def _period_ym(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")


class QuotaService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def ensure_defaults(self, tenant_id: str) -> None:
        tenant_uuid = UUID(str(tenant_id))
        policy = await self.db.scalar(
            select(TenantRateLimitPolicyModel).where(TenantRateLimitPolicyModel.tenant_id == tenant_uuid)
        )
        if policy is None:
            self.db.add(
                TenantRateLimitPolicyModel(
                    id=uuid4(),
                    tenant_id=tenant_uuid,
                    read_limit=self.settings.rate_limit_tenant_read,
                    write_limit=self.settings.rate_limit_tenant_write,
                    execute_limit=self.settings.rate_limit_tenant_execute,
                    user_read_limit=self.settings.rate_limit_user_read,
                    user_write_limit=self.settings.rate_limit_user_write,
                    user_execute_limit=self.settings.rate_limit_user_execute,
                    tenant_concurrency_limit=self.settings.concurrency_limit_tenant_execute,
                    user_concurrency_limit=self.settings.concurrency_limit_user_execute,
                    fail_mode=self.settings.rate_limit_fail_mode,
                )
            )

        quota = await self.db.scalar(
            select(TenantQuotaPolicyModel).where(TenantQuotaPolicyModel.tenant_id == tenant_uuid)
        )
        if quota is None:
            self.db.add(
                TenantQuotaPolicyModel(
                    id=uuid4(),
                    tenant_id=tenant_uuid,
                    monthly_token_quota=self.settings.quota_default_monthly_tokens,
                    enabled=True,
                )
            )
        await self.db.commit()

    async def get_limits(self, tenant_id: str) -> dict:
        tenant_uuid = UUID(str(tenant_id))
        await self.ensure_defaults(str(tenant_uuid))
        policy = await self.db.scalar(
            select(TenantRateLimitPolicyModel).where(TenantRateLimitPolicyModel.tenant_id == tenant_uuid)
        )
        quota = await self.db.scalar(
            select(TenantQuotaPolicyModel).where(TenantQuotaPolicyModel.tenant_id == tenant_uuid)
        )
        return {
            "tenant_id": str(tenant_uuid),
            "rate_limits": {
                "read": policy.read_limit,
                "write": policy.write_limit,
                "execute": policy.execute_limit,
                "user_read": policy.user_read_limit,
                "user_write": policy.user_write_limit,
                "user_execute": policy.user_execute_limit,
                "tenant_concurrency_limit": policy.tenant_concurrency_limit,
                "user_concurrency_limit": policy.user_concurrency_limit,
                "fail_mode": policy.fail_mode,
            },
            "quota": {
                "monthly_token_quota": quota.monthly_token_quota,
                "enabled": quota.enabled,
            },
        }

    async def get_effective_execute_policy(self, tenant_id: str) -> dict:
        tenant_uuid = UUID(str(tenant_id))
        await self.ensure_defaults(str(tenant_uuid))
        policy = await self.db.scalar(
            select(TenantRateLimitPolicyModel).where(TenantRateLimitPolicyModel.tenant_id == tenant_uuid)
        )
        return {
            "tenant_execute_limit": policy.execute_limit,
            "user_execute_limit": policy.user_execute_limit,
            "tenant_concurrency_limit": int(policy.tenant_concurrency_limit),
            "user_concurrency_limit": int(policy.user_concurrency_limit),
        }

    async def get_effective_rw_policy(self, tenant_id: str, bucket: str) -> dict:
        tenant_uuid = UUID(str(tenant_id))
        await self.ensure_defaults(str(tenant_uuid))
        policy = await self.db.scalar(
            select(TenantRateLimitPolicyModel).where(TenantRateLimitPolicyModel.tenant_id == tenant_uuid)
        )
        if bucket == "write":
            return {
                "tenant_limit": policy.write_limit,
                "user_limit": policy.user_write_limit,
            }
        return {
            "tenant_limit": policy.read_limit,
            "user_limit": policy.user_read_limit,
        }

    async def get_quota(self, tenant_id: str) -> dict:
        tenant_uuid = UUID(str(tenant_id))
        await self.ensure_defaults(str(tenant_uuid))
        quota = await self.db.scalar(
            select(TenantQuotaPolicyModel).where(TenantQuotaPolicyModel.tenant_id == tenant_uuid)
        )
        period = _period_ym()
        usage = await self.db.scalar(
            select(TenantQuotaUsageModel).where(
                TenantQuotaUsageModel.tenant_id == tenant_uuid,
                TenantQuotaUsageModel.period == period,
            )
        )
        used = usage.total_tokens if usage else 0
        monthly = quota.monthly_token_quota
        remaining = max(0, monthly - used)
        return {
            "tenant_id": str(tenant_uuid),
            "period": period,
            "enabled": quota.enabled,
            "monthly_token_quota": monthly,
            "used_tokens": used,
            "remaining_tokens": remaining,
            "prompt_tokens": usage.prompt_tokens if usage else 0,
            "completion_tokens": usage.completion_tokens if usage else 0,
            "request_count": usage.request_count if usage else 0,
        }

    async def update_limits(self, tenant_id: str, updates: dict) -> dict:
        tenant_uuid = UUID(str(tenant_id))
        await self.ensure_defaults(str(tenant_uuid))
        policy = await self.db.scalar(
            select(TenantRateLimitPolicyModel).where(TenantRateLimitPolicyModel.tenant_id == tenant_uuid)
        )
        for field in (
            "read_limit",
            "write_limit",
            "execute_limit",
            "user_read_limit",
            "user_write_limit",
            "user_execute_limit",
            "tenant_concurrency_limit",
            "user_concurrency_limit",
            "fail_mode",
        ):
            if field in updates:
                setattr(policy, field, updates[field])
        await self.db.commit()
        return await self.get_limits(str(tenant_uuid))

    async def update_quota(self, tenant_id: str, updates: dict) -> dict:
        tenant_uuid = UUID(str(tenant_id))
        await self.ensure_defaults(str(tenant_uuid))
        quota = await self.db.scalar(
            select(TenantQuotaPolicyModel).where(TenantQuotaPolicyModel.tenant_id == tenant_uuid)
        )
        if "monthly_token_quota" in updates:
            quota.monthly_token_quota = int(updates["monthly_token_quota"])
        if "enabled" in updates:
            quota.enabled = bool(updates["enabled"])
        await self.db.commit()
        return await self.get_quota(str(tenant_uuid))

    async def check_quota_or_raise(self, tenant_id: str) -> None:
        if not self.settings.quota_enforce_enabled:
            return
        current = await self.get_quota(tenant_id)
        if current["enabled"] and current["remaining_tokens"] <= 0:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=429,
                detail={
                    "detail": "quota_exceeded",
                    "quota": "monthly_tokens",
                    "remaining": 0,
                },
            )

    async def consume_tokens(self, tenant_id: str, prompt_tokens: int, completion_tokens: int) -> None:
        tenant_uuid = UUID(str(tenant_id))
        period = _period_ym()
        usage = await self.db.scalar(
            select(TenantQuotaUsageModel).where(
                TenantQuotaUsageModel.tenant_id == tenant_uuid,
                TenantQuotaUsageModel.period == period,
            )
        )
        total_add = max(0, int(prompt_tokens)) + max(0, int(completion_tokens))
        if usage is None:
            usage = TenantQuotaUsageModel(
                id=uuid4(),
                tenant_id=tenant_uuid,
                period=period,
                prompt_tokens=max(0, int(prompt_tokens)),
                completion_tokens=max(0, int(completion_tokens)),
                total_tokens=total_add,
                request_count=1,
            )
            self.db.add(usage)
        else:
            usage.prompt_tokens += max(0, int(prompt_tokens))
            usage.completion_tokens += max(0, int(completion_tokens))
            usage.total_tokens += total_add
            usage.request_count += 1
        await self.db.commit()
