import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from app.db import AsyncSessionLocal, engine, init_db
from app.models.db_models import (
    PlatformUserModel,
    SemanticCacheEntryModel,
    TenantMembershipModel,
    TenantModel,
)
from app.core.auth import get_current_user, require_admin
from app.routes.cache_admin import router as cache_admin_router


def _admin_headers(user_id: str, tenant_id: str) -> dict[str, str]:
    return {
        "X-User-Id": user_id,
        "X-User-Role": "admin",
        "X-Tenant-Id": tenant_id,
        "X-Tenant-Role": "owner",
    }


def _build_test_app(user_id: str, tenant_id: str) -> FastAPI:
    app = FastAPI()

    async def _override_user():
        return type(
            "Principal",
            (),
            {
                "user_id": user_id,
                "role": "admin",
                "tenant_id": tenant_id,
                "tenant_role": "owner",
            },
        )()

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[require_admin] = _override_user
    app.include_router(cache_admin_router)
    return app


@pytest.mark.asyncio
async def test_cache_me_stats_returns_current_tenant_only() -> None:
    await engine.dispose()
    await init_db()

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user_id = f"u-{uuid.uuid4()}"

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_a, name="tenant-a", status="active"))
        db.add(TenantModel(id=tenant_b, name="tenant-b", status="active"))
        db.add(PlatformUserModel(user_id=user_id, email="cache@example.com", role="admin"))
        await db.flush()
        db.add(TenantMembershipModel(tenant_id=tenant_a, user_id=user_id, role="owner", status="active"))
        db.add(
            SemanticCacheEntryModel(
                tenant_id=tenant_a,
                namespace="default",
                prompt_hash="hash-a",
                response="resp-a",
                cache_metadata={"hit_count": 5},
            )
        )
        db.add(
            SemanticCacheEntryModel(
                tenant_id=tenant_b,
                namespace="default",
                prompt_hash="hash-b",
                response="resp-b",
                cache_metadata={"hit_count": 11},
            )
        )
        await db.commit()

    app = _build_test_app(user_id=user_id, tenant_id=str(tenant_a))

    headers = _admin_headers(user_id=user_id, tenant_id=str(tenant_a))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/cache/me/stats", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenant_id"] == str(tenant_a)
    assert body["total_entries"] == 1
    assert body["total_hits"] == 5


@pytest.mark.asyncio
async def test_cache_admin_entries_rejects_cross_tenant_query() -> None:
    await engine.dispose()
    await init_db()

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user_id = f"u-{uuid.uuid4()}"

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_a, name="tenant-a", status="active"))
        db.add(TenantModel(id=tenant_b, name="tenant-b", status="active"))
        db.add(PlatformUserModel(user_id=user_id, email="cache@example.com", role="admin"))
        await db.flush()
        db.add(TenantMembershipModel(tenant_id=tenant_a, user_id=user_id, role="owner", status="active"))
        await db.commit()

    app = _build_test_app(user_id=user_id, tenant_id=str(tenant_a))

    headers = _admin_headers(user_id=user_id, tenant_id=str(tenant_a))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/admin/tenants/{tenant_b}/cache/entries", headers=headers)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Cross-tenant query is not allowed"


@pytest.mark.asyncio
async def test_cache_admin_invalidate_deletes_scoped_entries() -> None:
    await engine.dispose()
    await init_db()

    tenant_id = uuid.uuid4()
    user_id = f"u-{uuid.uuid4()}"

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_id, name="tenant-a", status="active"))
        db.add(PlatformUserModel(user_id=user_id, email="cache@example.com", role="admin"))
        await db.flush()
        db.add(TenantMembershipModel(tenant_id=tenant_id, user_id=user_id, role="owner", status="active"))
        db.add(
            SemanticCacheEntryModel(
                tenant_id=tenant_id,
                namespace="ns-1",
                prompt_hash="hash-a",
                response="resp-a",
                cache_metadata={"hit_count": 1},
            )
        )
        db.add(
            SemanticCacheEntryModel(
                tenant_id=tenant_id,
                namespace="ns-2",
                prompt_hash="hash-b",
                response="resp-b",
                cache_metadata={"hit_count": 2},
            )
        )
        await db.commit()

    app = _build_test_app(user_id=user_id, tenant_id=str(tenant_id))

    headers = _admin_headers(user_id=user_id, tenant_id=str(tenant_id))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            f"/admin/tenants/{tenant_id}/cache/invalidate",
            headers=headers,
            json={"namespace": "ns-1"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenant_id"] == str(tenant_id)
    assert body["namespace"] == "ns-1"
    assert body["deleted"] == 1

    async with AsyncSessionLocal() as db:
        remained = (
            await db.execute(
                select(SemanticCacheEntryModel).where(SemanticCacheEntryModel.tenant_id == tenant_id)
            )
        ).scalars().all()

    namespaces = sorted([row.namespace for row in remained])
    assert namespaces == ["ns-2"]
