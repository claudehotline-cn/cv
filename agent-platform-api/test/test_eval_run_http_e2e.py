import uuid

import httpx
import pytest
from fastapi import FastAPI

import app.routes.eval as eval_routes
from app.db import AsyncSessionLocal, engine, init_db
from app.models.db_models import AgentModel, PlatformUserModel, TenantMembershipModel, TenantModel
from app.routes.eval import router as eval_router


def _auth_headers(user_id: str, tenant_id: str) -> dict[str, str]:
    return {
        "X-User-Id": user_id,
        "X-User-Role": "admin",
        "X-Tenant-Id": tenant_id,
        "X-Tenant-Role": "owner",
    }


@pytest.mark.asyncio
async def test_eval_run_http_e2e(monkeypatch):
    await engine.dispose()
    await init_db()

    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    user_id = f"u-{uuid.uuid4()}"

    class _FakeGraph:
        async def ainvoke(self, inputs, config=None):
            content = ""
            if isinstance(inputs, dict):
                messages = inputs.get("messages")
                if isinstance(messages, list) and messages:
                    last = messages[-1]
                    if isinstance(last, dict):
                        content = str(last.get("content") or "")

            tool_name = "search" if "pass" in content else "unexpected_tool"
            return {
                "messages": [
                    {"role": "user", "content": content},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"name": tool_name, "arguments": {"q": content}}],
                    },
                    {"role": "assistant", "content": f"done:{content}"},
                ]
            }

    class _FakePlugin:
        def get_graph(self):
            return _FakeGraph()

    monkeypatch.setattr(
        eval_routes.registry,
        "get_plugin",
        lambda key: _FakePlugin() if key == "test_agent" else None,
    )

    async with AsyncSessionLocal() as db:
        db.add(TenantModel(id=tenant_id, name="eval-e2e-tenant", status="active"))
        db.add(PlatformUserModel(user_id=user_id, email="eval-e2e@example.com", role="admin"))
        db.add(AgentModel(id=agent_id, name="builtin-test", type="builtin", builtin_key="test_agent", config={}))
        await db.flush()
        db.add(TenantMembershipModel(tenant_id=tenant_id, user_id=user_id, role="owner", status="active"))
        await db.commit()

    app = FastAPI()
    app.include_router(eval_router)

    headers = _auth_headers(user_id=user_id, tenant_id=str(tenant_id))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        create_ds = await client.post(
            f"/agents/{agent_id}/eval/datasets",
            headers=headers,
            json={"name": "step6-e2e", "description": "http e2e"},
        )
        assert create_ds.status_code == 200, create_ds.text
        dataset_id = create_ds.json()["id"]

        import_cases = await client.post(
            f"/agents/{agent_id}/eval/datasets/{dataset_id}/import",
            headers=headers,
            json={
                "cases": [
                    {
                        "input": {"messages": [{"role": "user", "content": "please pass"}]},
                        "expected_output": {"tool_calls": [{"name": "search", "arguments": {"q": "please pass"}}]},
                    },
                    {
                        "input": {"messages": [{"role": "user", "content": "please fail"}]},
                        "expected_output": {"tool_calls": [{"name": "search", "arguments": {"q": "please fail"}}]},
                    },
                ]
            },
        )
        assert import_cases.status_code == 200, import_cases.text
        assert import_cases.json()["inserted"] == 2

        create_run = await client.post(
            f"/agents/{agent_id}/eval/runs",
            headers=headers,
            json={
                "dataset_id": dataset_id,
                "config": {"evaluators": ["trajectory_match"], "trajectory_match_mode": "strict"},
            },
        )
        assert create_run.status_code == 200, create_run.text
        run = create_run.json()
        assert run["status"] == "completed"
        assert run["summary"]["total"] == 2
        assert run["summary"]["passed"] == 1
        assert run["summary"]["failed"] == 1
        assert run["summary"]["errors"] == 0
        assert run["summary"]["avg_score"] == pytest.approx(0.5)

        run_id = run["id"]

        get_run = await client.get(
            f"/agents/{agent_id}/eval/runs/{run_id}",
            headers=headers,
        )
        assert get_run.status_code == 200, get_run.text
        assert get_run.json()["id"] == run_id

        list_results = await client.get(
            f"/agents/{agent_id}/eval/runs/{run_id}/results",
            headers=headers,
        )
        assert list_results.status_code == 200, list_results.text
        items = list_results.json()["items"]
        assert len(items) == 2
        statuses = sorted(item["status"] for item in items)
        assert statuses == ["failed", "passed"]

        scored = [item for item in items if "trajectory_match" in item.get("scores", {})]
        assert len(scored) == 2
        assert sorted(float(item["scores"]["trajectory_match"]) for item in scored) == [0.0, 1.0]
