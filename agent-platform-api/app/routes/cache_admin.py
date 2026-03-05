from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import AuthPrincipal, get_current_user, require_admin
from ..db import get_db
from ..models.db_models import SemanticCacheEntryModel
from ..services.tenant_shadow_service import TenantShadowService

router = APIRouter(tags=["cache"])


class InvalidateCacheRequest(BaseModel):
    namespace: Optional[str] = None


def _tenant_id_or_401(user: AuthPrincipal) -> str:
    tenant_id = (user.tenant_id or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant context required")
    try:
        UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant context") from exc
    return tenant_id


def _normalize_tenant_uuid_or_400(tenant_id: str) -> UUID:
    raw = (tenant_id or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Invalid tenant_id")
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant_id") from exc


async def _resolve_tenant_scope_or_403(
    user: AuthPrincipal,
    tenant_id: str,
    db: AsyncSession,
) -> UUID:
    current_tenant_uuid = UUID(_tenant_id_or_401(user))
    requested_tenant_uuid = _normalize_tenant_uuid_or_400(tenant_id)
    if requested_tenant_uuid != current_tenant_uuid:
        raise HTTPException(status_code=403, detail="Cross-tenant query is not allowed")

    has_membership = await TenantShadowService(db).has_active_membership(requested_tenant_uuid, user.user_id)
    if not has_membership:
        raise HTTPException(status_code=403, detail="Tenant membership required")

    return requested_tenant_uuid


def _normalize_namespace(namespace: Optional[str]) -> Optional[str]:
    if namespace is None:
        return None
    normalized = namespace.strip()
    return normalized or None


def _metadata_hit_count(cache_metadata: Any) -> int:
    if not isinstance(cache_metadata, dict):
        return 0
    raw = cache_metadata.get("hit_count")
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


@router.get("/cache/me/stats")
async def cache_stats_me(
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_uuid = UUID(_tenant_id_or_401(user))

    has_membership = await TenantShadowService(db).has_active_membership(tenant_uuid, user.user_id)
    if not has_membership:
        raise HTTPException(status_code=403, detail="Tenant membership required")

    total_entries_stmt = (
        select(func.count())
        .select_from(SemanticCacheEntryModel)
        .where(SemanticCacheEntryModel.tenant_id == tenant_uuid)
    )
    total_entries = int((await db.execute(total_entries_stmt)).scalar_one() or 0)

    hit_rows_stmt = select(SemanticCacheEntryModel.cache_metadata).where(
        SemanticCacheEntryModel.tenant_id == tenant_uuid
    )
    hit_rows = (await db.execute(hit_rows_stmt)).all()
    total_hits = sum(_metadata_hit_count(row[0]) for row in hit_rows)

    return {
        "tenant_id": str(tenant_uuid),
        "total_entries": total_entries,
        "total_hits": total_hits,
    }


@router.get("/admin/tenants/{tenant_id}/cache/entries")
async def list_cache_entries(
    tenant_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    namespace: Optional[str] = None,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scoped_tenant_uuid = await _resolve_tenant_scope_or_403(user, tenant_id, db)
    scoped_namespace = _normalize_namespace(namespace)

    stmt = select(SemanticCacheEntryModel).where(
        SemanticCacheEntryModel.tenant_id == scoped_tenant_uuid
    )
    if scoped_namespace is not None:
        stmt = stmt.where(SemanticCacheEntryModel.namespace == scoped_namespace)

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    rows_stmt = stmt.order_by(desc(SemanticCacheEntryModel.updated_at)).limit(limit).offset(offset)
    rows = (await db.execute(rows_stmt)).scalars().all()

    items = [
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "namespace": row.namespace,
            "prompt_hash": row.prompt_hash,
            "response": row.response,
            "metadata": row.cache_metadata or {},
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/admin/tenants/{tenant_id}/cache/invalidate")
async def invalidate_cache(
    tenant_id: str,
    body: Optional[InvalidateCacheRequest] = None,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    scoped_tenant_uuid = await _resolve_tenant_scope_or_403(user, tenant_id, db)
    scoped_namespace = _normalize_namespace(body.namespace if body else None)

    stmt = delete(SemanticCacheEntryModel).where(
        SemanticCacheEntryModel.tenant_id == scoped_tenant_uuid
    )
    if scoped_namespace is not None:
        stmt = stmt.where(SemanticCacheEntryModel.namespace == scoped_namespace)

    result = await db.execute(stmt)
    await db.commit()

    return {
        "tenant_id": str(scoped_tenant_uuid),
        "namespace": scoped_namespace,
        "deleted": int(result.rowcount or 0),
    }
