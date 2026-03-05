# Phase 2 SOLID Refactor (Guardrails + OTel + Semantic Cache) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a production-ready, SOLID-compliant execution pipeline that adds Guardrails, OpenTelemetry observability, and Semantic Cache without breaking existing multi-tenant, audit, and async worker flows.

**Architecture:** Use Ports & Adapters (hexagonal) with a single application orchestrator in `agent-core` and concrete adapters in `agent-platform-api`. API routes and worker call the orchestrator through dependency injection/composition root, not concrete services. Keep current database-init style (`init_db`) and contract-test style used by governance/prompt/eval modules.

**Tech Stack:** FastAPI, SQLAlchemy Async, PostgreSQL (JSONB, pgvector extension), Redis/ARQ, OpenTelemetry OTLP, Vue3 + Pinia + Element Plus.

---

### Task 1: Define SOLID Ports and decision models (no infra coupling)

**Files:**
- Create: `agent-core/agent_core/contracts/guardrails.py`
- Create: `agent-core/agent_core/contracts/semantic_cache.py`
- Create: `agent-core/agent_core/contracts/telemetry.py`
- Create: `agent-core/agent_core/application/models.py`
- Modify: `agent-core/agent_core/__init__.py`
- Test: `agent-platform-api/test/test_phase2_ports_contract.py`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_ports_contract.py
from agent_core.contracts.guardrails import GuardrailPort, GuardrailDecision
from agent_core.contracts.semantic_cache import SemanticCachePort
from agent_core.contracts.telemetry import TelemetryPort

def test_phase2_ports_exist_and_are_importable():
    assert GuardrailPort is not None
    assert SemanticCachePort is not None
    assert TelemetryPort is not None
    assert GuardrailDecision.__annotations__["action"]
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_ports_contract.py -q`
Expected: FAIL with `ModuleNotFoundError` / missing symbols.

**Step 3: Write minimal implementation**

```python
# agent-core/agent_core/contracts/guardrails.py
from dataclasses import dataclass
from typing import Literal, Protocol, Any

GuardrailAction = Literal["allow", "block", "redact", "require_approval"]

@dataclass
class GuardrailDecision:
    action: GuardrailAction
    reason_code: str
    sanitized_payload: Any | None = None

class GuardrailPort(Protocol):
    async def pre_input_check(self, input_payload: dict, ctx: dict) -> GuardrailDecision: ...
    async def pre_tool_check(self, tool_name: str, args: dict, ctx: dict) -> GuardrailDecision: ...
    async def post_output_check(self, output_payload: dict, ctx: dict) -> GuardrailDecision: ...
```

```python
# agent-core/agent_core/contracts/semantic_cache.py
from dataclasses import dataclass
from typing import Protocol, Any

@dataclass
class CacheLookupResult:
    hit: bool
    score: float
    payload: dict[str, Any] | None

class SemanticCachePort(Protocol):
    async def lookup(self, tenant_id: str, namespace: str, model_key: str, query_text: str, ctx: dict) -> CacheLookupResult: ...
    async def write(self, tenant_id: str, namespace: str, model_key: str, query_text: str, response_payload: dict, ctx: dict) -> None: ...
    async def invalidate(self, tenant_id: str, namespace: str | None = None) -> int: ...
    async def stats(self, tenant_id: str) -> dict: ...
```

```python
# agent-core/agent_core/contracts/telemetry.py
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from typing import Protocol

class TelemetryPort(Protocol):
    def start_span(self, name: str, attributes: dict | None = None) -> AbstractContextManager: ...
    def set_attributes(self, attributes: dict) -> None: ...
    def inc_counter(self, name: str, value: int = 1, attributes: dict | None = None) -> None: ...
    def observe_histogram(self, name: str, value: float, attributes: dict | None = None) -> None: ...
```

**Step 4: Run test to verify it passes**

Run: same pytest command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add agent-core/agent_core/contracts/guardrails.py agent-core/agent_core/contracts/semantic_cache.py agent-core/agent_core/contracts/telemetry.py agent-core/agent_core/application/models.py agent-core/agent_core/__init__.py agent-platform-api/test/test_phase2_ports_contract.py
git commit -m "feat: add phase2 ports and decision models for solid architecture"
```

---

### Task 2: Build application orchestrator in `agent-core` (single entrypoint)

**Files:**
- Create: `agent-core/agent_core/application/orchestrator.py`
- Create: `agent-core/agent_core/application/policy.py`
- Test: `agent-platform-api/test/test_phase2_orchestrator_contract.py`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_orchestrator_contract.py
import pytest
from agent_core.application.orchestrator import RequestExecutionOrchestrator

class _AllowAll:
    async def pre_input_check(self, input_payload, ctx):
        from agent_core.contracts.guardrails import GuardrailDecision
        return GuardrailDecision(action="allow", reason_code="ok")
    async def pre_tool_check(self, tool_name, args, ctx):
        from agent_core.contracts.guardrails import GuardrailDecision
        return GuardrailDecision(action="allow", reason_code="ok")
    async def post_output_check(self, output_payload, ctx):
        from agent_core.contracts.guardrails import GuardrailDecision
        return GuardrailDecision(action="allow", reason_code="ok")

class _MissCache:
    async def lookup(self, *args, **kwargs):
        from agent_core.contracts.semantic_cache import CacheLookupResult
        return CacheLookupResult(hit=False, score=0.0, payload=None)
    async def write(self, *args, **kwargs):
        return None

class _NoopTelemetry:
    def start_span(self, name, attributes=None):
        from contextlib import nullcontext
        return nullcontext()
    def set_attributes(self, attributes):
        return None
    def inc_counter(self, name, value=1, attributes=None):
        return None
    def observe_histogram(self, name, value, attributes=None):
        return None

@pytest.mark.asyncio
async def test_orchestrator_calls_executor_when_cache_miss():
    called = {"ok": False}

    async def _executor(ctx):
        called["ok"] = True
        return {"answer": "live"}

    orch = RequestExecutionOrchestrator(_AllowAll(), _MissCache(), _NoopTelemetry())
    out = await orch.execute(
        request={"query": "hello"},
        ctx={"tenant_id": "t1", "namespace": "chat", "model_key": "m1"},
        executor=_executor,
    )
    assert called["ok"] is True
    assert out["payload"]["answer"] == "live"
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_orchestrator_contract.py -q`
Expected: FAIL with missing orchestrator.

**Step 3: Write minimal implementation**

```python
# agent-core/agent_core/application/orchestrator.py
class RequestExecutionOrchestrator:
    def __init__(self, guardrails, semantic_cache, telemetry):
        self.guardrails = guardrails
        self.semantic_cache = semantic_cache
        self.telemetry = telemetry

    async def execute(self, request: dict, ctx: dict, executor):
        with self.telemetry.start_span("agent.run", attributes={"tenant.id": ctx.get("tenant_id", "")}):
            pre = await self.guardrails.pre_input_check(request, ctx)
            if pre.action == "block":
                return {"status": "blocked", "reason_code": pre.reason_code, "payload": pre.sanitized_payload}

            lookup = await self.semantic_cache.lookup(
                tenant_id=ctx["tenant_id"],
                namespace=ctx.get("namespace", "default"),
                model_key=ctx.get("model_key", "default"),
                query_text=request.get("query", ""),
                ctx=ctx,
            )
            if lookup.hit and lookup.payload is not None:
                self.telemetry.inc_counter("semantic_cache_hit_total", 1, {"tenant.id": ctx["tenant_id"]})
                return {"status": "cache_hit", "reason_code": "cache_hit", "payload": lookup.payload}

            live_payload = await executor(ctx)
            post = await self.guardrails.post_output_check(live_payload, ctx)
            payload = post.sanitized_payload if post.sanitized_payload is not None else live_payload

            if post.action in ("allow", "redact") and ctx.get("cacheable", True):
                await self.semantic_cache.write(
                    tenant_id=ctx["tenant_id"],
                    namespace=ctx.get("namespace", "default"),
                    model_key=ctx.get("model_key", "default"),
                    query_text=request.get("query", ""),
                    response_payload=payload,
                    ctx=ctx,
                )
            return {"status": post.action, "reason_code": post.reason_code, "payload": payload}
```

**Step 4: Run test to verify it passes**

Run: same pytest command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add agent-core/agent_core/application/orchestrator.py agent-core/agent_core/application/policy.py agent-platform-api/test/test_phase2_orchestrator_contract.py
git commit -m "feat: add phase2 execution orchestrator with guardrails cache and telemetry ports"
```

---

### Task 3: Add DB models + inline migrations for Guardrails/Cache (Phase 2 schema)

**Files:**
- Modify: `agent-platform-api/app/models/db_models.py`
- Modify: `agent-platform-api/app/db.py`
- Test: `agent-platform-api/test/test_phase2_migration_contract.py`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_migration_contract.py
import pytest
from sqlalchemy import text
from app.db import init_db, AsyncSessionLocal

@pytest.mark.asyncio
async def test_phase2_tables_exist_after_init_db():
    await init_db()
    async with AsyncSessionLocal() as db:
        for name in [
            "tenant_guardrail_policies",
            "guardrail_events",
            "semantic_cache_entries",
        ]:
            r = await db.execute(text("SELECT to_regclass(:name)"), {"name": name})
            assert r.scalar_one() == name
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_migration_contract.py -q`
Expected: FAIL because tables are missing.

**Step 3: Write minimal implementation**

```sql
-- agent-platform-api/app/db.py in init_db()
CREATE TABLE IF NOT EXISTS tenant_guardrail_policies (...);
CREATE TABLE IF NOT EXISTS guardrail_events (...);
CREATE TABLE IF NOT EXISTS semantic_cache_entries (...);
CREATE INDEX IF NOT EXISTS idx_sem_cache_tenant_ns_model ON semantic_cache_entries(tenant_id, namespace, model_key);
CREATE INDEX IF NOT EXISTS idx_guardrail_events_tenant_time ON guardrail_events(tenant_id, event_time DESC);
```

```python
# agent-platform-api/app/models/db_models.py
class TenantGuardrailPolicyModel(Base): ...
class GuardrailEventModel(Base): ...
class SemanticCacheEntryModel(Base): ...
```

Notes:
- Keep tenant FK and audit linkage style consistent with current models.
- For vector support, use migration-safe SQL: `CREATE EXTENSION IF NOT EXISTS vector` + `query_embedding VECTOR(1536)`.

**Step 4: Run test to verify it passes**

Run: same pytest command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add agent-platform-api/app/models/db_models.py agent-platform-api/app/db.py agent-platform-api/test/test_phase2_migration_contract.py
git commit -m "feat: add phase2 guardrail and semantic cache schema"
```

---

### Task 4: Implement infrastructure adapters (DB guardrails, pgvector cache, OTel telemetry)

**Files:**
- Create: `agent-platform-api/app/adapters/guardrails_db.py`
- Create: `agent-platform-api/app/adapters/cache_pgvector.py`
- Create: `agent-platform-api/app/adapters/telemetry_otel.py`
- Modify: `agent-core/agent_core/observability.py`
- Modify: `agent-core/agent_core/settings.py`
- Test: `agent-platform-api/test/test_phase2_adapters_contract.py`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_adapters_contract.py
from app.adapters.guardrails_db import DbGuardrailAdapter
from app.adapters.cache_pgvector import PgVectorSemanticCacheAdapter
from app.adapters.telemetry_otel import OTelTelemetryAdapter

def test_phase2_adapters_importable():
    assert DbGuardrailAdapter is not None
    assert PgVectorSemanticCacheAdapter is not None
    assert OTelTelemetryAdapter is not None
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_adapters_contract.py -q`
Expected: FAIL due to missing adapter modules.

**Step 3: Write minimal implementation**

```python
# app/adapters/telemetry_otel.py
class OTelTelemetryAdapter:
    # wrap tracer and meter
    # map to: start_span / set_attributes / inc_counter / observe_histogram
```

```python
# app/adapters/guardrails_db.py
class DbGuardrailAdapter:
    # load tenant_guardrail_policies
    # evaluate simple regex / keyword / pii toggles
    # persist guardrail_events for block/redact/approval
```

```python
# app/adapters/cache_pgvector.py
class PgVectorSemanticCacheAdapter:
    # embedding function via provider abstraction
    # cosine similarity search with tenant/model/namespace filter
    # write + hit_count update + ttl handling
```

```python
# agent-core/agent_core/settings.py (add envs)
otel_enabled: bool = Field(default=False, alias="OTEL_ENABLED")
otel_exporter_otlp_endpoint: str = Field(default="", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
otel_service_name: str = Field(default="agent-api", alias="OTEL_SERVICE_NAME")
otel_sample_rate: float = Field(default=1.0, alias="OTEL_SAMPLE_RATE")
otel_fail_mode: str = Field(default="open", alias="OTEL_FAIL_MODE")
semantic_cache_enabled: bool = Field(default=True, alias="SEMANTIC_CACHE_ENABLED")
semantic_cache_similarity_threshold: float = Field(default=0.86, alias="SEMANTIC_CACHE_SIMILARITY_THRESHOLD")
semantic_cache_ttl_seconds: int = Field(default=86400, alias="SEMANTIC_CACHE_TTL_SECONDS")
```

**Step 4: Run test to verify it passes**

Run: same pytest command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add agent-platform-api/app/adapters/guardrails_db.py agent-platform-api/app/adapters/cache_pgvector.py agent-platform-api/app/adapters/telemetry_otel.py agent-core/agent_core/observability.py agent-core/agent_core/settings.py agent-platform-api/test/test_phase2_adapters_contract.py
git commit -m "feat: implement phase2 adapters for guardrails cache and otel telemetry"
```

---

### Task 5: Add composition root and inject orchestrator in API startup

**Files:**
- Create: `agent-platform-api/app/composition_root.py`
- Modify: `agent-platform-api/app/main.py`
- Test: `agent-platform-api/test/test_phase2_composition_contract.py`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_composition_contract.py
from pathlib import Path

def test_main_registers_phase2_container():
    src = Path("/workspace/agent-platform-api/app/main.py").read_text(encoding="utf-8")
    assert "composition_root" in src
    assert "app.state.phase2" in src
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_composition_contract.py -q`
Expected: FAIL as composition root not wired.

**Step 3: Write minimal implementation**

```python
# app/composition_root.py
from dataclasses import dataclass

@dataclass
class Phase2Container:
    orchestrator: object
    guardrails: object
    semantic_cache: object
    telemetry: object

def build_phase2_container(db_factory):
    ...
```

```python
# app/main.py lifespan startup
from app.composition_root import build_phase2_container
app.state.phase2 = build_phase2_container(AsyncSessionLocal)
```

**Step 4: Run test to verify it passes**

Run: same pytest command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add agent-platform-api/app/composition_root.py agent-platform-api/app/main.py agent-platform-api/test/test_phase2_composition_contract.py
git commit -m "refactor: wire phase2 ports adapters via composition root"
```

---

### Task 6: Integrate orchestrator into chat/rag/tasks routes and worker

**Files:**
- Modify: `agent-platform-api/app/routes/chat.py`
- Modify: `agent-platform-api/app/routes/rag.py`
- Modify: `agent-platform-api/app/routes/tasks.py`
- Modify: `agent-platform-api/app/worker.py`
- Test: `agent-platform-api/test/test_phase2_pipeline_hooks_contract.py`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_pipeline_hooks_contract.py
from pathlib import Path

TARGETS = [
    "/workspace/agent-platform-api/app/routes/chat.py",
    "/workspace/agent-platform-api/app/routes/rag.py",
    "/workspace/agent-platform-api/app/routes/tasks.py",
    "/workspace/agent-platform-api/app/worker.py",
]

def test_phase2_orchestrator_hook_present_in_main_flows():
    for f in TARGETS:
        src = Path(f).read_text(encoding="utf-8")
        assert "orchestrator" in src
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_pipeline_hooks_contract.py -q`
Expected: FAIL before integration.

**Step 3: Write minimal implementation**

```python
# route example
container = request.app.state.phase2
result = await container.orchestrator.execute(
    request={"query": message},
    ctx={"tenant_id": user.tenant_id, "namespace": "chat", "model_key": agent_key, "cacheable": True},
    executor=_run_agent_live,
)
```

Worker requirement:
- Use same orchestrator call path in `agent_execute_task` and `agent_resume_task` to keep behavior consistent.
- Keep existing quota/concurrency and audit lifecycle events intact.

**Step 4: Run test to verify it passes**

Run: same pytest command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add agent-platform-api/app/routes/chat.py agent-platform-api/app/routes/rag.py agent-platform-api/app/routes/tasks.py agent-platform-api/app/worker.py agent-platform-api/test/test_phase2_pipeline_hooks_contract.py
git commit -m "feat: connect phase2 orchestrator to api routes and async worker"
```

---

### Task 7: Add Guardrails management and audit query APIs

**Files:**
- Create: `agent-platform-api/app/routes/guardrails.py`
- Modify: `agent-platform-api/app/routes/audit.py`
- Modify: `agent-platform-api/app/main.py`
- Test: `agent-platform-api/test/test_phase2_guardrails_api_contract.py`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_guardrails_api_contract.py
from pathlib import Path

def test_guardrails_routes_registered():
    src = Path("/workspace/agent-platform-api/app/main.py").read_text(encoding="utf-8")
    assert "guardrails" in src
    assert "app.include_router(guardrails.router)" in src
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_guardrails_api_contract.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
# app/routes/guardrails.py
@router.get("/guardrails/me")
async def get_my_guardrails(...): ...

@router.get("/admin/tenants/{tenant_id}/guardrails")
@router.put("/admin/tenants/{tenant_id}/guardrails")

# app/routes/audit.py
@router.get("/guardrails")
async def list_guardrail_events(...): ...
```

**Step 4: Run test to verify it passes**

Run: same pytest command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add agent-platform-api/app/routes/guardrails.py agent-platform-api/app/routes/audit.py agent-platform-api/app/main.py agent-platform-api/test/test_phase2_guardrails_api_contract.py
git commit -m "feat: add guardrails policy and audit event apis"
```

---

### Task 8: Add Semantic Cache admin and stats APIs

**Files:**
- Create: `agent-platform-api/app/routes/cache_admin.py`
- Modify: `agent-platform-api/app/main.py`
- Test: `agent-platform-api/test/test_phase2_cache_api_contract.py`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_cache_api_contract.py
from pathlib import Path

def test_cache_routes_registered():
    src = Path("/workspace/agent-platform-api/app/main.py").read_text(encoding="utf-8")
    assert "cache_admin" in src
    assert "app.include_router(cache_admin.router)" in src
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_cache_api_contract.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
# app/routes/cache_admin.py
@router.get("/cache/me/stats")
async def cache_stats_me(...): ...

@router.get("/admin/tenants/{tenant_id}/cache/entries")
async def list_cache_entries(...): ...

@router.post("/admin/tenants/{tenant_id}/cache/invalidate")
async def invalidate_cache(...): ...
```

**Step 4: Run test to verify it passes**

Run: same pytest command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add agent-platform-api/app/routes/cache_admin.py agent-platform-api/app/main.py agent-platform-api/test/test_phase2_cache_api_contract.py
git commit -m "feat: add semantic cache stats and admin invalidation apis"
```

---

### Task 9: Frontend minimal pages and API bindings

**Files:**
- Modify: `agent-chat-vue/src/api/client.ts`
- Modify: `agent-chat-vue/src/router.ts`
- Modify: `agent-chat-vue/src/views/settings/SecurityCenterView.vue`
- Create: `agent-chat-vue/src/views/settings/CacheMetricsView.vue`
- Modify: `agent-chat-vue/src/stores/security.ts`
- Test: `agent-platform-api/test/test_phase2_frontend_contract.py`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_frontend_contract.py
from pathlib import Path

def test_frontend_routes_include_cache_metrics():
    src = Path("/workspace/agent-chat-vue/src/router.ts").read_text(encoding="utf-8")
    assert "SettingsCacheMetrics" in src
    assert "CacheMetricsView.vue" in src
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_frontend_contract.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**

```ts
// client.ts add
getMyGuardrails()
updateTenantGuardrails(...)
listGuardrailAudit(...)
getCacheStatsMe()
listTenantCacheEntries(...)
invalidateTenantCache(...)
```

```ts
// router.ts add settings child route
{
  path: 'cache-metrics',
  name: 'SettingsCacheMetrics',
  component: () => import('./views/settings/CacheMetricsView.vue'),
}
```

`SecurityCenterView.vue`:
- add quick action button to `/settings/cache-metrics`
- show guardrail status summary card (enabled, last updated)

`CacheMetricsView.vue`:
- show hit rate, avg latency gain, invalidation action (admin only)

**Step 4: Run test to verify it passes**

Run: same pytest command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add agent-chat-vue/src/api/client.ts agent-chat-vue/src/router.ts agent-chat-vue/src/views/settings/SecurityCenterView.vue agent-chat-vue/src/views/settings/CacheMetricsView.vue agent-chat-vue/src/stores/security.ts agent-platform-api/test/test_phase2_frontend_contract.py
git commit -m "feat: add phase2 guardrails and cache metrics ui"
```

---

### Task 10: OTel metrics and trace assertions (verification-focused)

**Files:**
- Test: `agent-platform-api/test/test_phase2_otel_contract.py`
- Modify: `agent-platform-api/app/adapters/telemetry_otel.py`
- Modify: `agent-core/agent_core/observability.py`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_otel_contract.py
from pathlib import Path

REQUIRED_NAMES = [
    "agent_run_duration_ms",
    "tool_call_duration_ms",
    "agent_errors_total",
    "llm_tokens_prompt_total",
    "llm_tokens_completion_total",
    "llm_cost_usd_total",
]

def test_otel_metric_names_declared():
    src = Path("/workspace/agent-platform-api/app/adapters/telemetry_otel.py").read_text(encoding="utf-8")
    for name in REQUIRED_NAMES:
        assert name in src
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_otel_contract.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**

- declare and emit the six metric names exactly
- map API root span (`http.request`) and orchestrator span (`agent.run`)
- wrap tool call and rag proxy sections with child spans

**Step 4: Run test to verify it passes**

Run: same pytest command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add agent-platform-api/test/test_phase2_otel_contract.py agent-platform-api/app/adapters/telemetry_otel.py agent-core/agent_core/observability.py
git commit -m "feat: add phase2 otel metrics and span conventions"
```

---

### Task 11: End-to-end contract verification in container

**Files:**
- Test: `agent-platform-api/test/test_phase2_end_to_end_contract.py`
- Modify: `scripts/run-agent-tests.sh`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_end_to_end_contract.py
import pytest

@pytest.mark.asyncio
async def test_phase2_minimum_contract_placeholder():
    # to be replaced with real API-level e2e in this task
    assert False, "implement e2e"
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_end_to_end_contract.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**

Implement e2e assertions:
- policy block case returns blocked decision and logs guardrail event
- cache hit second request path
- trace id/request id correlation in audit

Update `scripts/run-agent-tests.sh` to include phase2 contract subset.

**Step 4: Run test to verify it passes**

Run:
- `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_end_to_end_contract.py -q`
- `bash scripts/run-agent-tests.sh`
Expected: all relevant phase2 tests PASS.

**Step 5: Commit**

```bash
git add agent-platform-api/test/test_phase2_end_to_end_contract.py scripts/run-agent-tests.sh
git commit -m "test: add phase2 end to end contract verification"
```

---

### Task 12: Documentation and operator runbook

**Files:**
- Modify: `docs/production_readiness.md`
- Create: `docs/design/phase2_solid_ports_adapters.md`
- Modify: `CLAUDE.md`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_docs_contract.py
from pathlib import Path

def test_phase2_docs_include_env_and_rollout_steps():
    doc = Path('/workspace/docs/production_readiness.md').read_text(encoding='utf-8')
    assert 'OTEL_ENABLED' in doc
    assert 'SEMANTIC_CACHE_SIMILARITY_THRESHOLD' in doc
    assert 'tenant_guardrail_policies' in doc
```

**Step 2: Run test to verify it fails**

Run: `docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_docs_contract.py -q`
Expected: FAIL.

**Step 3: Write minimal implementation**

- Add rollout guide:
  - env vars
  - migration smoke check SQL
  - dashboard minimum set
  - fallback (`OTEL_FAIL_MODE=open`, guardrails disabled per tenant)
- Add architecture note to `CLAUDE.md` under Phase 2 section with files and responsibilities.

**Step 4: Run test to verify it passes**

Run: same pytest command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add docs/production_readiness.md docs/design/phase2_solid_ports_adapters.md CLAUDE.md agent-platform-api/test/test_phase2_docs_contract.py
git commit -m "docs: add phase2 solid architecture and operator runbook"
```

---

## Full Verification Checklist (run before merge)

1. Targeted phase2 tests:

```bash
docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_phase2_* -q
```

Expected: all phase2 contract tests PASS.

2. Existing governance/eval regression:

```bash
docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api" agent-test pytest /workspace/agent-platform-api/test/test_governance_m2_contract.py /workspace/agent-platform-api/test/test_eval_routes_contract.py /workspace/agent-platform-api/test/test_prompt_ab_eval_migration_contract.py -q
```

Expected: PASS; no regression in existing modules.

3. Frontend build:

```bash
cd agent-chat-vue && npm run build
```

Expected: successful Vite build with new settings route/page.

4. Smoke endpoints:

```bash
curl -fsS http://localhost:18111/health
curl -fsS http://localhost:18111/guardrails/me -H "Authorization: Bearer <token>"
curl -fsS http://localhost:18111/cache/me/stats -H "Authorization: Bearer <token>"
```

Expected: 200 for health and auth-protected endpoints with valid token.

---

## Notes for execution discipline

- Use `@superpowers:test-driven-development` when implementing each task.
- Use `@superpowers:systematic-debugging` for any failed contract.
- Keep each commit scoped to exactly one task.
- Do not introduce extra abstractions beyond ports/orchestrator/adapters required by this plan.
- Preserve existing auth/quota/governance semantics while integrating orchestrator.
