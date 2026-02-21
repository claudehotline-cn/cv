import os
from typing import Any, Dict
from uuid import UUID

import httpx
from sqlalchemy import select
from fastapi import APIRouter, Body, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from agent_auth_client import AuthClient
from agent_core.settings import get_settings

from ..core.auth import AuthPrincipal, get_current_user
from ..db import get_db
from ..models.db_models import TenantMembershipModel, TenantModel
from ..services.tenant_shadow_service import TenantShadowService
from ..services.user_shadow_service import UserShadowService


router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_base_url() -> str:
    return (os.getenv("AGENT_AUTH_URL") or "http://agent-auth:8000").rstrip("/")


async def _proxy(method: str, path: str, body: Dict[str, Any] | None = None, auth: str | None = None):
    url = _auth_base_url() + path
    headers: Dict[str, str] = {}
    if auth:
        headers["Authorization"] = auth

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(method, url, json=body, headers=headers)

    try:
        data = resp.json()
    except Exception:
        data = {"detail": resp.text or "Upstream error"}

    if resp.status_code >= 400:
        detail = data.get("detail", data)
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return data


@router.post("/register")
async def register(body: Dict[str, Any] = Body(...)):
    return await _proxy("POST", "/auth/register", body=body)


@router.post("/login")
async def login(body: Dict[str, Any] = Body(...)):
    return await _proxy("POST", "/auth/login", body=body)


@router.post("/refresh")
async def refresh(body: Dict[str, Any] = Body(...)):
    return await _proxy("POST", "/auth/refresh", body=body)


@router.post("/logout")
async def logout(body: Dict[str, Any] = Body(...)):
    return await _proxy("POST", "/auth/logout", body=body)


@router.post("/logout-all")
async def logout_all(authorization: str | None = Header(default=None)):
    return await _proxy("POST", "/auth/logout-all", auth=authorization)


@router.get("/me")
async def me(authorization: str | None = Header(default=None)):
    data = await _proxy("GET", "/auth/me", auth=authorization)
    if not authorization:
        return data

    try:
        principal = await AuthClient(get_settings().auth_introspection_url).introspect(authorization=authorization)
        if isinstance(data, dict):
            data["tenant_id"] = principal.tenant_id
            data["tenant_role"] = principal.tenant_role
    except Exception:
        # Keep /auth/me available even if introspection is temporarily unavailable.
        pass

    return data


@router.post("/change-password")
async def change_password(body: Dict[str, Any] = Body(...), authorization: str | None = Header(default=None)):
    return await _proxy("POST", "/auth/change-password", body=body, auth=authorization)


@router.post("/api-keys")
async def create_api_key(body: Dict[str, Any] = Body(...), authorization: str | None = Header(default=None)):
    return await _proxy("POST", "/auth/api-keys", body=body, auth=authorization)


@router.get("/api-keys")
async def list_api_keys(authorization: str | None = Header(default=None)):
    return await _proxy("GET", "/auth/api-keys", auth=authorization)


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, authorization: str | None = Header(default=None)):
    return await _proxy("DELETE", f"/auth/api-keys/{key_id}", auth=authorization)


@router.get("/tenants")
async def list_my_tenants(
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    tenant_id = user.tenant_id or settings.auth_default_tenant_id
    try:
        tenant_uuid = UUID(str(tenant_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant context") from exc
    tenant_service = TenantShadowService(db)
    await UserShadowService(db).ensure_user(user.user_id, user.email, user.role)
    await tenant_service.ensure_tenant(str(tenant_id))
    await tenant_service.ensure_membership(tenant_id=tenant_uuid, user_id=user.user_id, role=user.role)

    stmt = (
        select(TenantMembershipModel, TenantModel)
        .join(TenantModel, TenantMembershipModel.tenant_id == TenantModel.id)
        .where(
            TenantMembershipModel.user_id == user.user_id,
            TenantMembershipModel.status == "active",
            TenantModel.status == "active",
        )
        .order_by(TenantModel.created_at.asc())
    )
    rows = (await db.execute(stmt)).all()
    items = [
        {
            "id": str(member.tenant_id),
            "name": tenant.name,
            "role": member.role,
            "status": member.status,
        }
        for member, tenant in rows
    ]
    return {
        "items": items,
        "active_tenant_id": str(tenant_id),
    }
