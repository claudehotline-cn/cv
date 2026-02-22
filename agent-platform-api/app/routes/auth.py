import os
from typing import Any, Dict, Optional
from uuid import UUID

import httpx
from sqlalchemy import select, func
from fastapi import APIRouter, Body, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from agent_auth_client import AuthClient
from agent_core.settings import get_settings

from ..core.auth import AuthPrincipal, get_current_user
from ..db import get_db
from ..models.db_models import PlatformUserModel, TenantMembershipModel, TenantModel


router = APIRouter(prefix="/auth", tags=["auth"])


ALLOWED_TENANT_ROLES = {"owner", "admin", "member"}


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
    requested_tenant_id = user.tenant_id or settings.auth_default_tenant_id
    try:
        requested_tenant_uuid = UUID(str(requested_tenant_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant context") from exc

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

    active_tenant_id = str(requested_tenant_uuid)
    membership_ids = {item["id"] for item in items}
    if active_tenant_id not in membership_ids and items:
        active_tenant_id = items[0]["id"]

    return {
        "items": items,
        "active_tenant_id": active_tenant_id,
    }


def _normalize_tenant_role(value: Optional[str]) -> str:
    role = (value or "").strip().lower()
    if role not in ALLOWED_TENANT_ROLES:
        raise HTTPException(status_code=400, detail="Invalid tenant role")
    return role


async def _get_active_membership(db: AsyncSession, tenant_uuid: UUID, user_id: str) -> Optional[TenantMembershipModel]:
    return await db.scalar(
        select(TenantMembershipModel).where(
            TenantMembershipModel.tenant_id == tenant_uuid,
            TenantMembershipModel.user_id == user_id,
            TenantMembershipModel.status == "active",
        )
    )


async def _ensure_tenant_access(
    db: AsyncSession,
    user: AuthPrincipal,
    tenant_id: str,
    *,
    require_manager: bool,
) -> UUID:
    try:
        tenant_uuid = UUID(str(tenant_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant context") from exc

    tenant = await db.scalar(
        select(TenantModel).where(
            TenantModel.id == tenant_uuid,
            TenantModel.status == "active",
        )
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    membership = await _get_active_membership(db, tenant_uuid, user.user_id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Tenant membership required")

    if require_manager and membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Tenant admin required")

    return tenant_uuid


def _member_name(email: Optional[str], user_id: str) -> str:
    if email and "@" in email:
        return email.split("@", 1)[0]
    return user_id


@router.get("/tenants/{tenant_id}/members")
async def list_tenant_members(
    tenant_id: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_uuid = await _ensure_tenant_access(db, user, tenant_id, require_manager=False)

    stmt = (
        select(TenantMembershipModel, PlatformUserModel)
        .join(PlatformUserModel, PlatformUserModel.user_id == TenantMembershipModel.user_id)
        .where(TenantMembershipModel.tenant_id == tenant_uuid)
        .order_by(TenantMembershipModel.created_at.asc())
    )
    rows = (await db.execute(stmt)).all()
    return {
        "tenant_id": str(tenant_uuid),
        "items": [
            {
                "user_id": membership.user_id,
                "name": _member_name(platform_user.email, membership.user_id),
                "email": platform_user.email,
                "role": membership.role,
                "status": membership.status,
                "created_at": membership.created_at,
            }
            for membership, platform_user in rows
        ],
    }


@router.post("/tenants/{tenant_id}/members/invite")
async def invite_tenant_member(
    tenant_id: str,
    body: Dict[str, Any] = Body(...),
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_uuid = await _ensure_tenant_access(db, user, tenant_id, require_manager=True)

    role = _normalize_tenant_role(body.get("role") or "member")
    target_user_id = str(body.get("user_id") or "").strip()
    target_email = str(body.get("email") or "").strip().lower()
    if not target_user_id and not target_email:
        raise HTTPException(status_code=400, detail="user_id or email is required")

    target_user: Optional[PlatformUserModel] = None
    if target_user_id:
        target_user = await db.scalar(select(PlatformUserModel).where(PlatformUserModel.user_id == target_user_id))
    elif target_email:
        target_user = await db.scalar(select(PlatformUserModel).where(func.lower(PlatformUserModel.email) == target_email))

    if target_user is None:
        raise HTTPException(status_code=404, detail="Target user not found")

    target_user_id = target_user.user_id
    membership = await db.scalar(
        select(TenantMembershipModel).where(
            TenantMembershipModel.tenant_id == tenant_uuid,
            TenantMembershipModel.user_id == target_user_id,
        )
    )
    if membership is None:
        membership = TenantMembershipModel(
            tenant_id=tenant_uuid,
            user_id=target_user_id,
            role=role,
            status="active",
        )
        db.add(membership)
    else:
        membership.role = role
        membership.status = "active"

    await db.commit()
    await db.refresh(membership)
    return {
        "tenant_id": str(tenant_uuid),
        "user_id": membership.user_id,
        "name": _member_name(target_user.email, membership.user_id),
        "email": target_user.email,
        "role": membership.role,
        "status": membership.status,
        "created_at": membership.created_at,
    }


async def _ensure_not_last_owner(
    db: AsyncSession,
    tenant_uuid: UUID,
    member_user_id: str,
) -> None:
    owner_count = await db.scalar(
        select(func.count(TenantMembershipModel.id)).where(
            TenantMembershipModel.tenant_id == tenant_uuid,
            TenantMembershipModel.status == "active",
            TenantMembershipModel.role == "owner",
        )
    )
    member = await db.scalar(
        select(TenantMembershipModel).where(
            TenantMembershipModel.tenant_id == tenant_uuid,
            TenantMembershipModel.user_id == member_user_id,
            TenantMembershipModel.status == "active",
        )
    )
    if member and member.role == "owner" and (owner_count or 0) <= 1:
        raise HTTPException(status_code=400, detail="Cannot modify the last active owner")


@router.patch("/tenants/{tenant_id}/members/{member_user_id}")
async def update_tenant_member_role(
    tenant_id: str,
    member_user_id: str,
    body: Dict[str, Any] = Body(...),
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_uuid = await _ensure_tenant_access(db, user, tenant_id, require_manager=True)
    role = _normalize_tenant_role(body.get("role"))

    membership = await db.scalar(
        select(TenantMembershipModel).where(
            TenantMembershipModel.tenant_id == tenant_uuid,
            TenantMembershipModel.user_id == member_user_id,
            TenantMembershipModel.status == "active",
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found")

    if membership.role != role:
        if membership.role == "owner" and role != "owner":
            await _ensure_not_last_owner(db, tenant_uuid, member_user_id)
        membership.role = role
        await db.commit()
        await db.refresh(membership)

    platform_user = await db.scalar(select(PlatformUserModel).where(PlatformUserModel.user_id == member_user_id))
    return {
        "tenant_id": str(tenant_uuid),
        "user_id": membership.user_id,
        "name": _member_name(platform_user.email if platform_user else None, membership.user_id),
        "email": platform_user.email if platform_user else None,
        "role": membership.role,
        "status": membership.status,
        "created_at": membership.created_at,
    }


@router.delete("/tenants/{tenant_id}/members/{member_user_id}")
async def remove_tenant_member(
    tenant_id: str,
    member_user_id: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_uuid = await _ensure_tenant_access(db, user, tenant_id, require_manager=True)

    membership = await db.scalar(
        select(TenantMembershipModel).where(
            TenantMembershipModel.tenant_id == tenant_uuid,
            TenantMembershipModel.user_id == member_user_id,
            TenantMembershipModel.status == "active",
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found")

    await _ensure_not_last_owner(db, tenant_uuid, member_user_id)
    membership.status = "inactive"
    await db.commit()

    return {
        "tenant_id": str(tenant_uuid),
        "user_id": member_user_id,
        "removed": True,
    }
