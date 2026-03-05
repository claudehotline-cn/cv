import sys
import uuid
from types import ModuleType, SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI


if "agent_auth_client" not in sys.modules:
    fake_agent_auth_client = ModuleType("agent_auth_client")

    class _AuthClient:
        def __init__(self, _url: str):
            self._url = _url

        async def introspect(self, authorization: str):
            _ = authorization
            raise RuntimeError("auth introspection is not used in dev-header tests")

    setattr(fake_agent_auth_client, "AuthClient", _AuthClient)
    sys.modules["agent_auth_client"] = fake_agent_auth_client

if "redis" not in sys.modules:
    fake_redis = ModuleType("redis")
    fake_redis_asyncio = ModuleType("redis.asyncio")

    class _FakeRedisClient:
        async def incr(self, *_unused_args, **_unused_kwargs):
            return 1

        async def expire(self, *_unused_args, **_unused_kwargs):
            return True

        async def decr(self, *_unused_args, **_unused_kwargs):
            return 0

        async def get(self, *_unused_args, **_unused_kwargs):
            return None

        async def delete(self, *_unused_args, **_unused_kwargs):
            return 1

        async def close(self):
            return None

    def _from_url(*_unused_args, **_unused_kwargs):
        return _FakeRedisClient()

    setattr(fake_redis_asyncio, "from_url", _from_url)
    setattr(fake_redis, "asyncio", fake_redis_asyncio)
    sys.modules["redis"] = fake_redis
    sys.modules["redis.asyncio"] = fake_redis_asyncio

if "arq" not in sys.modules:
    fake_arq = ModuleType("arq")

    async def _create_pool(*_unused_args, **_unused_kwargs):
        raise RuntimeError("arq pool should not be used when orchestrator blocks")

    setattr(fake_arq, "create_pool", _create_pool)
    sys.modules["arq"] = fake_arq

if "arq.connections" not in sys.modules:
    fake_arq_connections = ModuleType("arq.connections")

    class _RedisSettings:
        @classmethod
        def from_dsn(cls, _dsn):
            return cls()

    setattr(fake_arq_connections, "RedisSettings", _RedisSettings)
    sys.modules["arq.connections"] = fake_arq_connections

if "app.services.secrets_service" not in sys.modules:
    fake_secrets_service = ModuleType("app.services.secrets_service")

    class _SecretsService:
        def __init__(self, _db):
            self._db = _db

    setattr(fake_secrets_service, "SecretsService", _SecretsService)
    sys.modules["app.services.secrets_service"] = fake_secrets_service

if "app.services.secrets_injector" not in sys.modules:
    fake_secrets_injector = ModuleType("app.services.secrets_injector")

    class _RuntimeSecretInjector:
        def __init__(self, _service):
            self._service = _service

        async def resolve(self, **_kwargs):
            return []

        def inject(self, runtime_config, resolved):
            _ = resolved
            return runtime_config

    setattr(fake_secrets_injector, "RuntimeSecretInjector", _RuntimeSecretInjector)
    sys.modules["app.services.secrets_injector"] = fake_secrets_injector

import app.routes.tasks as tasks_routes
from app.db import AsyncSessionLocal, engine, init_db
from app.models.db_models import (
    AgentModel,
    GuardrailEventModel,
    PlatformUserModel,
    SessionModel,
    TenantMembershipModel,
    TenantModel,
)
from app.routes.audit import router as audit_router
from app.routes.tasks import router as tasks_router


def _admin_headers(user_id: str, tenant_id: str) -> dict[str, str]:
    return {
        "X-User-Id": user_id,
        "X-User-Role": "admin",
        "X-Tenant-Id": tenant_id,
        "X-Tenant-Role": "owner",
    }


@pytest.mark.asyncio
async def test_phase2_tasks_execute_returns_403_when_orchestrator_blocked(monkeypatch) -> None:
    await engine.dispose()
    await init_db()

    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user_id = f"u-{uuid.uuid4()}"

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_id, name="phase2-tenant", status="active"))
        db.add(PlatformUserModel(user_id=user_id, email="phase2-e2e@example.com", role="admin"))
        await db.flush()
        db.add(TenantMembershipModel(tenant_id=tenant_id, user_id=user_id, role="owner", status="active"))
        db.add(
            SessionModel(
                id=session_id,
                tenant_id=tenant_id,
                user_id=user_id,
                title="phase2-e2e-session",
                state={"owner_user_id": user_id},
            )
        )
        await db.commit()

    async def _no_rate_limit(*_unused_args, **_unused_kwargs):
        return None

    async def _acquire_ok(*_unused_args, **_unused_kwargs):
        return True, "tenant"

    async def _release_noop(*_unused_args, **_unused_kwargs):
        return None

    async def _blocked_orchestrator(_request, _ctx, _executor):
        return {
            "status": "blocked",
            "reason_code": "policy_input_block",
            "payload": {"blocked": True},
        }

    monkeypatch.setattr(tasks_routes, "enforce_rate_limit", _no_rate_limit)
    monkeypatch.setattr(tasks_routes, "acquire_execute_concurrency", _acquire_ok)
    monkeypatch.setattr(tasks_routes, "release_execute_concurrency", _release_noop)

    app = FastAPI()
    app.state.phase2 = SimpleNamespace(orchestrator=_blocked_orchestrator, telemetry=object())
    app.include_router(tasks_router)

    headers = _admin_headers(user_id=user_id, tenant_id=str(tenant_id))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            f"/tasks/sessions/{session_id}/execute",
            headers=headers,
            json={"message": "should be blocked"},
        )

    assert resp.status_code == 403, resp.text
    assert resp.json() == {
        "detail": {
            "detail": "orchestrator_blocked",
            "reason_code": "policy_input_block",
        }
    }


@pytest.mark.asyncio
async def test_phase2_guardrails_audit_defaults_to_current_tenant_scope() -> None:
    await engine.dispose()
    await init_db()

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user_id = f"u-{uuid.uuid4()}"

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_a, name="tenant-a", status="active"))
        db.add(TenantModel(id=tenant_b, name="tenant-b", status="active"))
        db.add(PlatformUserModel(user_id=user_id, email="guardrails-e2e@example.com", role="admin"))
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
async def test_phase2_guardrails_audit_rejects_cross_tenant_query() -> None:
    await engine.dispose()
    await init_db()

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user_id = f"u-{uuid.uuid4()}"

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_a, name="tenant-a", status="active"))
        db.add(TenantModel(id=tenant_b, name="tenant-b", status="active"))
        db.add(PlatformUserModel(user_id=user_id, email="guardrails-e2e@example.com", role="admin"))
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
async def test_phase2_chat_resume_rejects_tenant_without_membership(monkeypatch) -> None:
    await engine.dispose()
    await init_db()

    tenant_a = uuid.uuid4()
    outsider_user_id = f"outsider-{uuid.uuid4()}"
    owner_user_id = f"owner-{uuid.uuid4()}"
    target_session_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_a, name="tenant-a", status="active"))
        db.add(PlatformUserModel(user_id=owner_user_id, email="owner@example.com", role="admin"))
        db.add(PlatformUserModel(user_id=outsider_user_id, email="outsider@example.com", role="admin"))
        await db.flush()
        db.add(TenantMembershipModel(tenant_id=tenant_a, user_id=owner_user_id, role="owner", status="active"))
        db.add(
            AgentModel(
                id=agent_id,
                name="data-agent",
                type="builtin",
                builtin_key="data_agent",
                config={},
            )
        )
        db.add(
            SessionModel(
                id=target_session_id,
                tenant_id=tenant_a,
                user_id=owner_user_id,
                agent_id=agent_id,
                title="owner-session",
                state={"owner_user_id": owner_user_id},
            )
        )
        await db.commit()

    async def _fake_orchestrator(_request, _ctx, _executor):
        return {
            "status": "ok",
            "reason_code": None,
            "payload": {"graph": object(), "inputs": {}, "config": {}},
        }

    class _FakeGraph:
        async def astream(self, *_args, **_kwargs):
            if False:
                yield None

    class _FakePlugin:
        def get_graph(self):
            return _FakeGraph()

    if "app.core.agent_registry" not in sys.modules:
        fake_registry = ModuleType("app.core.agent_registry")
        setattr(fake_registry, "registry", SimpleNamespace(get_plugin=lambda _key: _FakePlugin()))
        sys.modules["app.core.agent_registry"] = fake_registry

    import app.routes.chat as chat_routes

    monkeypatch.setattr(chat_routes, "registry", SimpleNamespace(get_plugin=lambda _key: _FakePlugin()))

    app = FastAPI()
    app.state.event_bus = SimpleNamespace(redis=object())
    app.state.phase2 = SimpleNamespace(orchestrator=_fake_orchestrator, telemetry=object())
    app.include_router(chat_routes.router)

    headers = _admin_headers(user_id=outsider_user_id, tenant_id=str(tenant_a))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            f"/sessions/{target_session_id}/resume",
            headers=headers,
            json={"decision": "approve", "feedback": "ok"},
        )

    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_phase2_chat_resume_rejects_cross_tenant_session(monkeypatch) -> None:
    await engine.dispose()
    await init_db()

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    owner_user_id = f"owner-{uuid.uuid4()}"
    attacker_user_id = f"attacker-{uuid.uuid4()}"
    target_session_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_a, name="tenant-a", status="active"))
        db.add(TenantModel(id=tenant_b, name="tenant-b", status="active"))
        db.add(PlatformUserModel(user_id=owner_user_id, email="owner@example.com", role="admin"))
        db.add(PlatformUserModel(user_id=attacker_user_id, email="attacker@example.com", role="admin"))
        await db.flush()
        db.add(TenantMembershipModel(tenant_id=tenant_a, user_id=owner_user_id, role="owner", status="active"))
        db.add(TenantMembershipModel(tenant_id=tenant_b, user_id=attacker_user_id, role="owner", status="active"))
        db.add(
            AgentModel(
                id=agent_id,
                name="data-agent",
                type="builtin",
                builtin_key="data_agent",
                config={},
            )
        )
        db.add(
            SessionModel(
                id=target_session_id,
                tenant_id=tenant_a,
                user_id=owner_user_id,
                agent_id=agent_id,
                title="owner-session",
                state={"owner_user_id": owner_user_id},
            )
        )
        await db.commit()

    async def _fake_orchestrator(_request, _ctx, _executor):
        return {
            "status": "ok",
            "reason_code": None,
            "payload": {"graph": object(), "inputs": {}, "config": {}},
        }

    class _FakeGraph:
        async def astream(self, *_args, **_kwargs):
            if False:
                yield None

    class _FakePlugin:
        def get_graph(self):
            return _FakeGraph()

    if "app.core.agent_registry" not in sys.modules:
        fake_registry = ModuleType("app.core.agent_registry")
        setattr(fake_registry, "registry", SimpleNamespace(get_plugin=lambda _key: _FakePlugin()))
        sys.modules["app.core.agent_registry"] = fake_registry

    import app.routes.chat as chat_routes

    monkeypatch.setattr(chat_routes, "registry", SimpleNamespace(get_plugin=lambda _key: _FakePlugin()))

    app = FastAPI()
    app.state.event_bus = SimpleNamespace(redis=object())
    app.state.phase2 = SimpleNamespace(orchestrator=_fake_orchestrator, telemetry=object())
    app.include_router(chat_routes.router)

    headers = _admin_headers(user_id=attacker_user_id, tenant_id=str(tenant_b))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            f"/sessions/{target_session_id}/resume",
            headers=headers,
            json={"decision": "approve", "feedback": "ok"},
        )

    assert resp.status_code in {403, 404}, resp.text
