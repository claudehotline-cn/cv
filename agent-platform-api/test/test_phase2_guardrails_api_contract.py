import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.db import AsyncSessionLocal, engine, init_db
from app.models.db_models import GuardrailEventModel, PlatformUserModel, TenantMembershipModel, TenantModel
from app.routes.audit import router as audit_router


def _admin_headers(user_id: str, tenant_id: str) -> dict[str, str]:
    return {
        "X-User-Id": user_id,
        "X-User-Role": "admin",
        "X-Tenant-Id": tenant_id,
        "X-Tenant-Role": "owner",
    }


@pytest.mark.asyncio
async def test_audit_guardrails_defaults_to_current_tenant_scope() -> None:
    await engine.dispose()
    await init_db()

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user_id = f"u-{uuid.uuid4()}"

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_a, name="tenant-a", status="active"))
        db.add(TenantModel(id=tenant_b, name="tenant-b", status="active"))
        db.add(PlatformUserModel(user_id=user_id, email="guardrails@example.com", role="admin"))
        await db.flush()
        db.add(TenantMembershipModel(tenant_id=tenant_a, user_id=user_id, role="owner", status="active"))
        db.add(
            GuardrailEventModel(
                tenant_id=tenant_a,
                direction="input",
                action="allow",
                reason_code="safe",
                payload={"source": "tenant-a"},
            )
        )
        db.add(
            GuardrailEventModel(
                tenant_id=tenant_b,
                direction="output",
                action="block",
                reason_code="pii",
                payload={"source": "tenant-b"},
            )
        )
        await db.commit()

    app = FastAPI()
    app.include_router(audit_router)

    headers = _admin_headers(user_id=user_id, tenant_id=str(tenant_a))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/audit/guardrails", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["tenant_id"] == str(tenant_a)


@pytest.mark.asyncio
async def test_audit_guardrails_rejects_cross_tenant_query_for_non_platform_super_admin() -> None:
    await engine.dispose()
    await init_db()

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user_id = f"u-{uuid.uuid4()}"

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_a, name="tenant-a", status="active"))
        db.add(TenantModel(id=tenant_b, name="tenant-b", status="active"))
        db.add(PlatformUserModel(user_id=user_id, email="guardrails@example.com", role="admin"))
        await db.flush()
        db.add(TenantMembershipModel(tenant_id=tenant_a, user_id=user_id, role="owner", status="active"))
        await db.commit()

    app = FastAPI()
    app.include_router(audit_router)

    headers = _admin_headers(user_id=user_id, tenant_id=str(tenant_a))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/audit/guardrails?tenant_id={tenant_b}", headers=headers)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Cross-tenant query is not allowed"


@pytest.mark.asyncio
async def test_audit_guardrails_invalid_tenant_id_returns_400() -> None:
    await engine.dispose()
    await init_db()

    tenant_a = uuid.uuid4()
    user_id = f"u-{uuid.uuid4()}"

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_a, name="tenant-a", status="active"))
        db.add(PlatformUserModel(user_id=user_id, email="guardrails@example.com", role="admin"))
        await db.flush()
        db.add(TenantMembershipModel(tenant_id=tenant_a, user_id=user_id, role="owner", status="active"))
        await db.commit()

    app = FastAPI()
    app.include_router(audit_router)

    headers = _admin_headers(user_id=user_id, tenant_id=str(tenant_a))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/audit/guardrails?tenant_id=not-a-uuid", headers=headers)

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "Invalid tenant_id"
