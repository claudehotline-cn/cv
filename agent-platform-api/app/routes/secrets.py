from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import AuthPrincipal, get_current_user, require_admin
from agent_core.settings import get_settings
from ..db import get_db
from ..services.secrets_service import SecretsService
from ..services.tenant_shadow_service import TenantShadowService
from arq import create_pool
from arq.connections import RedisSettings


router = APIRouter(prefix="/secrets", tags=["secrets"])


class CreateSecretRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1)
    scope: str = Field(default="user", pattern="^(user|tenant)$")
    provider: Optional[str] = None


class RotateSecretRequest(BaseModel):
    value: str = Field(min_length=1)


class ReencryptTenantSecretsRequest(BaseModel):
    tenant_id: Optional[str] = None


def _is_tenant_admin(user: AuthPrincipal) -> bool:
    return (user.tenant_role or "").lower() in ("owner", "admin")


async def _ensure_membership_or_403(db: AsyncSession, user: AuthPrincipal, tenant_id: str) -> None:
    from uuid import UUID

    try:
        tenant_uuid = UUID(str(tenant_id))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant context") from exc
    if not await TenantShadowService(db).has_active_membership(tenant_uuid, user.user_id):
        raise HTTPException(status_code=403, detail="Tenant membership required")


@router.post("/")
async def create_secret(
    body: CreateSecretRequest,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = user.tenant_id
    await _ensure_membership_or_403(db, user, str(tenant_id))
    if body.scope == "tenant" and not _is_tenant_admin(user):
        raise HTTPException(status_code=403, detail="Tenant admin required")

    owner_user_id = user.user_id if body.scope == "user" else None
    try:
        rec = await SecretsService(db).create_secret(
            tenant_id=str(tenant_id),
            owner_user_id=owner_user_id,
            scope=body.scope,
            name=body.name,
            provider=body.provider,
            plaintext_value=body.value,
        )
        return rec.__dict__
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/")
async def list_secrets(
    scope: Optional[str] = None,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = user.tenant_id
    await _ensure_membership_or_403(db, user, str(tenant_id))
    rows = await SecretsService(db).list_secrets(
        tenant_id=str(tenant_id),
        owner_user_id=user.user_id,
        scope=scope,
    )
    return {"items": [r.__dict__ for r in rows]}


@router.get("/{secret_id}")
async def get_secret(
    secret_id: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = user.tenant_id
    await _ensure_membership_or_403(db, user, str(tenant_id))
    try:
        rec = await SecretsService(db).get_secret_metadata(
            tenant_id=str(tenant_id),
            secret_id=secret_id,
            user_id=user.user_id,
            is_admin=_is_tenant_admin(user),
        )
        return rec.__dict__
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{secret_id}/rotate")
async def rotate_secret(
    secret_id: str,
    body: RotateSecretRequest,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = user.tenant_id
    await _ensure_membership_or_403(db, user, str(tenant_id))
    try:
        rec = await SecretsService(db).rotate_secret(
            tenant_id=str(tenant_id),
            secret_id=secret_id,
            user_id=user.user_id,
            is_admin=_is_tenant_admin(user),
            plaintext_value=body.value,
        )
        return rec.__dict__
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{secret_id}/disable")
async def disable_secret(
    secret_id: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = user.tenant_id
    await _ensure_membership_or_403(db, user, str(tenant_id))
    try:
        rec = await SecretsService(db).set_secret_status(
            tenant_id=str(tenant_id),
            secret_id=secret_id,
            user_id=user.user_id,
            is_admin=_is_tenant_admin(user),
            status="disabled",
        )
        return rec.__dict__
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{secret_id}/enable")
async def enable_secret(
    secret_id: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = user.tenant_id
    await _ensure_membership_or_403(db, user, str(tenant_id))
    try:
        rec = await SecretsService(db).set_secret_status(
            tenant_id=str(tenant_id),
            secret_id=secret_id,
            user_id=user.user_id,
            is_admin=_is_tenant_admin(user),
            status="active",
        )
        return rec.__dict__
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{secret_id}")
async def delete_secret(
    secret_id: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = user.tenant_id
    await _ensure_membership_or_403(db, user, str(tenant_id))
    try:
        rec = await SecretsService(db).set_secret_status(
            tenant_id=str(tenant_id),
            secret_id=secret_id,
            user_id=user.user_id,
            is_admin=_is_tenant_admin(user),
            status="deleted",
        )
        return rec.__dict__
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/admin/tenants/{tenant_id}")
async def admin_list_tenant_secrets(
    tenant_id: str,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = await SecretsService(db).list_secrets(
        tenant_id=str(tenant_id),
        owner_user_id=None,
        scope=None,
    )
    return {"items": [r.__dict__ for r in rows]}


@router.post("/admin/tenants/{tenant_id}")
async def admin_create_tenant_secret(
    tenant_id: str,
    body: CreateSecretRequest,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if body.scope != "tenant":
        raise HTTPException(status_code=400, detail="Admin tenant secret must use scope=tenant")
    try:
        rec = await SecretsService(db).create_secret(
            tenant_id=str(tenant_id),
            owner_user_id=None,
            scope="tenant",
            name=body.name,
            provider=body.provider,
            plaintext_value=body.value,
        )
        return rec.__dict__
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/tenants/{tenant_id}/reencrypt")
async def admin_reencrypt_tenant_secrets(
    tenant_id: str,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _ = db
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        job = await redis.enqueue_job("secrets_reencrypt_tenant", str(tenant_id))
    finally:
        await redis.close()
    return {
        "tenant_id": tenant_id,
        "queued": True,
        "job_id": getattr(job, "job_id", None),
    }
