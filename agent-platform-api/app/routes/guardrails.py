from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import AuthPrincipal, get_current_user, require_admin
from ..db import get_db
from ..models.db_models import TenantGuardrailPolicyModel


# Backed by tenant_guardrail_policies.
router = APIRouter(tags=["guardrails"])


class UpdateGuardrailPolicyRequest(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


def _tenant_uuid_or_401(tenant_id: str | None) -> UUID:
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant context required")
    try:
        return UUID(str(tenant_id))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant context") from exc


def _normalize_mode_or_400(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in {"monitor", "enforce"}:
        raise HTTPException(status_code=400, detail="Invalid guardrail mode")
    return normalized


def _serialize_policy(policy: TenantGuardrailPolicyModel | None, tenant_id: UUID) -> Dict[str, Any]:
    if policy is None:
        return {
            "tenant_id": str(tenant_id),
            "enabled": True,
            "mode": "enforce",
            "config": {},
        }

    return {
        "tenant_id": str(policy.tenant_id),
        "enabled": bool(policy.enabled),
        "mode": policy.mode,
        "config": dict(policy.config or {}),
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
    }


@router.get("/guardrails/me")
async def get_my_guardrails(
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_uuid = _tenant_uuid_or_401(user.tenant_id)
    policy = await db.scalar(
        select(TenantGuardrailPolicyModel).where(TenantGuardrailPolicyModel.tenant_id == tenant_uuid)
    )
    return _serialize_policy(policy, tenant_uuid)


@router.get("/admin/tenants/{tenant_id}/guardrails")
async def get_tenant_guardrails(
    tenant_id: str,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_uuid = _tenant_uuid_or_401(tenant_id)
    policy = await db.scalar(
        select(TenantGuardrailPolicyModel).where(TenantGuardrailPolicyModel.tenant_id == tenant_uuid)
    )
    return _serialize_policy(policy, tenant_uuid)


@router.put("/admin/tenants/{tenant_id}/guardrails")
async def update_tenant_guardrails(
    tenant_id: str,
    body: UpdateGuardrailPolicyRequest,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_uuid = _tenant_uuid_or_401(tenant_id)
    policy = await db.scalar(
        select(TenantGuardrailPolicyModel).where(TenantGuardrailPolicyModel.tenant_id == tenant_uuid)
    )

    if policy is None:
        policy = TenantGuardrailPolicyModel(
            tenant_id=tenant_uuid,
            enabled=True,
            mode="enforce",
            config={},
        )
        db.add(policy)

    if body.enabled is not None:
        policy.enabled = body.enabled
    if body.mode is not None:
        policy.mode = _normalize_mode_or_400(body.mode)
    if body.config is not None:
        policy.config = dict(body.config)

    await db.commit()
    await db.refresh(policy)
    return _serialize_policy(policy, tenant_uuid)
