# Phase2 Cache Admin + Frontend + Docs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver Phase2 remaining scope by adding semantic cache admin APIs (#16), wiring frontend settings cache metrics and security center entry (#14), then updating runbook/docs (#10) with verification evidence.

**Architecture:** Keep backend changes inside `agent-platform-api` with route-level auth/tenant scoping that matches existing guardrails/audit patterns. Frontend changes stay in `agent-chat-vue` using current `api/client.ts` + Pinia security store + settings routing conventions. Implement in strict TDD steps (RED→GREEN) and preserve existing Phase2 behavior.

**Tech Stack:** FastAPI, SQLAlchemy Async, PostgreSQL JSONB/pgvector, Vue3, Pinia, Element Plus, pytest in `agent-test` container.

---

### Task 1: Add backend contract test for cache admin routes (#16)

**Files:**
- Create: `agent-platform-api/test/test_phase2_cache_api_contract.py`
- Read reference: `agent-platform-api/test/test_phase2_guardrails_api_contract.py`

**Step 1: Write the failing test**

```python
# agent-platform-api/test/test_phase2_cache_api_contract.py
from pathlib import Path


def test_cache_routes_registered_in_main() -> None:
    src = Path('/workspace/agent-platform-api/app/main.py').read_text(encoding='utf-8')
    assert 'cache_admin' in src
    assert 'app.include_router(cache_admin.router)' in src
```

**Step 2: Run test to verify it fails**

Run:
`docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api:/workspace/agent-auth-client" agent-test pytest /workspace/agent-platform-api/test/test_phase2_cache_api_contract.py -q`

Expected: FAIL (router not registered yet).

**Step 3: Commit**

```bash
git add agent-platform-api/test/test_phase2_cache_api_contract.py
git commit -m "test: add failing contract for phase2 cache admin routes"
```

---

### Task 2: Implement cache admin API routes and registration (#16)

**Files:**
- Create: `agent-platform-api/app/routes/cache_admin.py`
- Modify: `agent-platform-api/app/main.py`
- Test: `agent-platform-api/test/test_phase2_cache_api_contract.py`

**Step 1: Write minimal route implementation**

```python
# app/routes/cache_admin.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import AuthPrincipal, get_current_user, require_admin
from ..db import get_db
from ..models.db_models import SemanticCacheEntryModel

router = APIRouter(tags=["cache"])

@router.get("/cache/me/stats")
async def cache_stats_me(...):
    ...

@router.get("/admin/tenants/{tenant_id}/cache/entries")
async def list_cache_entries(...):
    ...

@router.post("/admin/tenants/{tenant_id}/cache/invalidate")
async def invalidate_cache(...):
    ...
```

Implementation constraints:
- Validate tenant UUID format (`400` on invalid).
- Enforce same-tenant scope unless same tenant as user (`403` on cross-tenant).
- `cache/me/stats` returns at least: `tenant_id`, `total_entries`, `total_hits`.
- `list` supports `limit/offset` with newest-first ordering.
- `invalidate` supports optional `namespace` filter and returns delete count.

**Step 2: Register router in main**

```python
from app.routes import ..., cache_admin
...
app.include_router(cache_admin.router)
```

**Step 3: Run contract test to verify it passes**

Run:
`docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api:/workspace/agent-auth-client" agent-test pytest /workspace/agent-platform-api/test/test_phase2_cache_api_contract.py -q`

Expected: PASS.

**Step 4: Commit**

```bash
git add agent-platform-api/app/routes/cache_admin.py agent-platform-api/app/main.py agent-platform-api/test/test_phase2_cache_api_contract.py
git commit -m "feat: add phase2 semantic cache admin and stats apis"
```

---

### Task 3: Add behavior-level cache API tests (tenant isolation + stats/invalidate)

**Files:**
- Modify: `agent-platform-api/test/test_phase2_cache_api_contract.py`
- Read reference: `agent-platform-api/test/test_phase2_guardrails_api_contract.py`

**Step 1: Write failing behavior tests**

Add tests with real DB setup + `FastAPI` + `httpx.ASGITransport`:
- `test_cache_me_stats_returns_current_tenant_only`
- `test_cache_admin_entries_rejects_cross_tenant_query`
- `test_cache_admin_invalidate_deletes_scoped_entries`

Each test creates tenant/user/membership + `semantic_cache_entries` rows and asserts API behavior.

**Step 2: Run tests to verify failures (if implementation incomplete)**

Run:
`docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api:/workspace/agent-auth-client" agent-test pytest /workspace/agent-platform-api/test/test_phase2_cache_api_contract.py -q`

Expected: at least one FAIL before final code fix.

**Step 3: Implement minimal backend fixes**

- Adjust SQL/filters/response fields only as needed for tests.
- Do not refactor unrelated routes.

**Step 4: Re-run tests to verify pass**

Run same command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add agent-platform-api/test/test_phase2_cache_api_contract.py agent-platform-api/app/routes/cache_admin.py
git commit -m "test: enforce tenant-scoped behavior for phase2 cache apis"
```

---

### Task 4: Add frontend contract test for cache metrics route + view (#14)

**Files:**
- Create: `agent-platform-api/test/test_phase2_frontend_contract.py`

**Step 1: Write the failing test**

```python
from pathlib import Path


def test_frontend_routes_include_cache_metrics() -> None:
    src = Path('/workspace/agent-chat-vue/src/router.ts').read_text(encoding='utf-8')
    assert 'SettingsCacheMetrics' in src
    assert 'CacheMetricsView.vue' in src
```

**Step 2: Run test to verify it fails**

Run:
`docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api:/workspace/agent-auth-client" agent-test pytest /workspace/agent-platform-api/test/test_phase2_frontend_contract.py -q`

Expected: FAIL.

**Step 3: Commit**

```bash
git add agent-platform-api/test/test_phase2_frontend_contract.py
git commit -m "test: add failing frontend contract for phase2 cache metrics route"
```

---

### Task 5: Implement frontend API bindings + route + cache metrics page (#14)

**Files:**
- Modify: `agent-chat-vue/src/api/client.ts`
- Modify: `agent-chat-vue/src/router.ts`
- Modify: `agent-chat-vue/src/stores/security.ts`
- Modify: `agent-chat-vue/src/views/settings/SecurityCenterView.vue`
- Create: `agent-chat-vue/src/views/settings/CacheMetricsView.vue`
- Test: `agent-platform-api/test/test_phase2_frontend_contract.py`

**Step 1: Add client methods**

Add typed methods in `api/client.ts`:
- `getCacheStatsMe()`
- `listTenantCacheEntries(tenantId: string, params?: { limit?: number; offset?: number; namespace?: string })`
- `invalidateTenantCache(tenantId: string, payload?: { namespace?: string })`
- `getMyGuardrails()` (if missing)

**Step 2: Add store state/actions**

In `stores/security.ts` add:
- state: `cacheStats`, `cacheEntries`, `cacheLoading`
- actions: `loadCacheStats()`, `loadCacheEntries()`, `invalidateCache(namespace?)`

**Step 3: Add route and page**

In `router.ts` add settings child route:

```ts
{
  path: 'cache-metrics',
  name: 'SettingsCacheMetrics',
  component: () => import('./views/settings/CacheMetricsView.vue'),
}
```

Create `CacheMetricsView.vue` minimal page:
- hit summary cards (`total_entries`, `total_hits`)
- table/list for recent entries
- invalidate button (admin only)

**Step 4: Add Security Center quick action**

In `SecurityCenterView.vue` add button navigating to `/settings/cache-metrics`.

**Step 5: Run frontend contract test**

Run:
`docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api:/workspace/agent-auth-client" agent-test pytest /workspace/agent-platform-api/test/test_phase2_frontend_contract.py -q`

Expected: PASS.

**Step 6: Run frontend build**

Run:
`docker exec agent-chat-vue npm run build`

Expected: build succeeds.

**Step 7: Commit**

```bash
git add agent-chat-vue/src/api/client.ts agent-chat-vue/src/router.ts agent-chat-vue/src/stores/security.ts agent-chat-vue/src/views/settings/SecurityCenterView.vue agent-chat-vue/src/views/settings/CacheMetricsView.vue agent-platform-api/test/test_phase2_frontend_contract.py
git commit -m "feat: add phase2 cache metrics settings page and client bindings"
```

---

### Task 6: Update docs/runbook for Phase2 completion (#10)

**Files:**
- Modify: `docs/production_readiness.md`
- Modify: `CLAUDE.md`
- (Optional if missing) Create: `docs/design/phase2_solid_ports_adapters.md`
- Create: `agent-platform-api/test/test_phase2_docs_contract.py`

**Step 1: Write failing docs contract**

```python
from pathlib import Path


def test_phase2_docs_include_cache_and_guardrail_ops() -> None:
    doc = Path('/workspace/docs/production_readiness.md').read_text(encoding='utf-8')
    assert 'OTEL_ENABLED' in doc
    assert '/cache/me/stats' in doc
    assert '/admin/tenants/{tenant_id}/cache/invalidate' in doc
    assert '/guardrails/me' in doc
```

**Step 2: Run test to verify it fails**

Run:
`docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api:/workspace/agent-auth-client" agent-test pytest /workspace/agent-platform-api/test/test_phase2_docs_contract.py -q`

Expected: FAIL.

**Step 3: Update docs minimally**

Add to runbook:
- new cache admin endpoints + auth scope
- guardrails endpoints + auth scope
- rollout checklist and smoke curl commands
- fallback guidance (`OTEL_FAIL_MODE=open`, tenant policy toggles)

**Step 4: Re-run docs contract**

Run same command as Step 2.
Expected: PASS.

**Step 5: Commit**

```bash
git add docs/production_readiness.md CLAUDE.md docs/design/phase2_solid_ports_adapters.md agent-platform-api/test/test_phase2_docs_contract.py
git commit -m "docs: finalize phase2 runbook for cache guardrails and otel operations"
```

---

## Full Verification Checklist (before declaring done)

1) Backend phase2 contracts and e2e:

```bash
docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api:/workspace/agent-auth-client" agent-test pytest /workspace/agent-platform-api/test/test_phase2_cache_api_contract.py /workspace/agent-platform-api/test/test_phase2_guardrails_api_contract.py /workspace/agent-platform-api/test/test_phase2_pipeline_hooks_contract.py /workspace/agent-platform-api/test/test_phase2_orchestrator_contract.py /workspace/agent-platform-api/test/test_phase2_e2e.py -q
```

2) Frontend contract + build:

```bash
docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api:/workspace/agent-auth-client" agent-test pytest /workspace/agent-platform-api/test/test_phase2_frontend_contract.py -q
docker exec agent-chat-vue npm run build
```

3) Docs contract:

```bash
docker exec -e PYTHONPATH="/workspace/agent-audit:/workspace/agent-core:/workspace/agent-test:/workspace/agent-platform-api:/workspace/agent-auth-client" agent-test pytest /workspace/agent-platform-api/test/test_phase2_docs_contract.py -q
```

Expected: all PASS.
