from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import AuthPrincipal, get_current_user, require_admin
from ..db import get_db
from ..services.quota_service import QuotaService


router = APIRouter(prefix="/limits", tags=["limits"])
quota_router = APIRouter(prefix="/quota", tags=["limits"])


class UpdateTenantLimitsRequest(BaseModel):
    read_limit: str | None = None
    write_limit: str | None = None
    execute_limit: str | None = None
    user_read_limit: str | None = None
    user_write_limit: str | None = None
    user_execute_limit: str | None = None
    tenant_concurrency_limit: int | None = Field(default=None, ge=1)
    user_concurrency_limit: int | None = Field(default=None, ge=1)
    fail_mode: str | None = None


class UpdateTenantQuotaRequest(BaseModel):
    monthly_token_quota: int | None = Field(default=None, ge=0)
    enabled: bool | None = None


@router.get("/me")
async def get_my_limits(
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = user.tenant_id
    data = await QuotaService(db).get_limits(str(tenant_id))
    data["user_id"] = user.user_id
    return data


@router.get("/quota/me")
async def get_my_quota(
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = user.tenant_id
    data = await QuotaService(db).get_quota(str(tenant_id))
    data["user_id"] = user.user_id
    return data


@quota_router.get("/me")
async def get_my_quota_alias(
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = user.tenant_id
    data = await QuotaService(db).get_quota(str(tenant_id))
    data["user_id"] = user.user_id
    return data


@router.get("/admin/tenants/{tenant_id}")
async def get_tenant_limits(
    tenant_id: str,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await QuotaService(db).get_limits(tenant_id)


@router.get("/admin/tenants/{tenant_id}/quota")
async def get_tenant_quota(
    tenant_id: str,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await QuotaService(db).get_quota(tenant_id)


@router.put("/admin/tenants/{tenant_id}")
async def update_tenant_limits(
    tenant_id: str,
    body: UpdateTenantLimitsRequest,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await QuotaService(db).update_limits(tenant_id, body.model_dump(exclude_none=True))


@router.put("/admin/tenants/{tenant_id}/quota")
async def update_tenant_quota(
    tenant_id: str,
    body: UpdateTenantQuotaRequest,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await QuotaService(db).update_quota(tenant_id, body.model_dump(exclude_none=True))
