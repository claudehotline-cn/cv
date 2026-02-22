from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import AuthPrincipal, get_current_user, require_admin
from ..db import get_db
from ..services.quota_service import QuotaService


router = APIRouter(prefix="/limits", tags=["limits"])


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
