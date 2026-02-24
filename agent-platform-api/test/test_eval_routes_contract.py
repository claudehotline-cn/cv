import pytest
from uuid import UUID, uuid4

from app.core.auth import AuthPrincipal
from app.db import AsyncSessionLocal, init_db
from sqlalchemy import select

from app.models.db_models import (
    AgentModel,
    EvalDatasetModel,
    EvalResultModel,
    PlatformUserModel,
    TenantMembershipModel,
    TenantModel,
)
import app.routes.eval as eval_routes
from app.routes.eval import (
    CreateDatasetRequest,
    CreateRunRequest,
    ImportCasesRequest,
    create_eval_dataset,
    create_eval_run,
    import_eval_cases,
)


@pytest.mark.asyncio
async def test_create_eval_dataset_contract():
    await init_db()

    tenant_id = uuid4()
    agent_id = uuid4()
    user_id = f"u-{uuid4()}"

    async with AsyncSessionLocal() as db:
        tenant = TenantModel(id=tenant_id, name="t1", status="active")
        user = PlatformUserModel(user_id=user_id, email="u@example.com", role="admin")
        agent = AgentModel(id=agent_id, name="a1", type="custom", config={})

        db.add(tenant)
        db.add(user)
        db.add(agent)
        await db.flush()

        db.add(TenantMembershipModel(tenant_id=tenant_id, user_id=user_id, role="owner", status="active"))
        await db.commit()

        principal = AuthPrincipal(user_id=user_id, role="admin", tenant_id=str(tenant_id), tenant_role="owner")
        out = await create_eval_dataset(
            agent_id=str(agent_id),
            body=CreateDatasetRequest(name="dataset-1", description="d"),
            user=principal,
            db=db,
        )

        assert out["name"] == "dataset-1"
        assert out["description"] == "d"
        assert out["agent_id"] == str(agent_id)

        ds = (await db.execute(
            select(EvalDatasetModel).where(EvalDatasetModel.id == out["id"])
        )).scalar_one()
        assert str(ds.tenant_id) == str(tenant_id)


@pytest.mark.asyncio
async def test_create_eval_run_executes_cases_and_persists_results(monkeypatch):
    await init_db()

    tenant_id = uuid4()
    agent_id = uuid4()
    user_id = f"u-{uuid4()}"

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
        tenant = TenantModel(id=tenant_id, name="t1", status="active")
        user = PlatformUserModel(user_id=user_id, email="u@example.com", role="admin")
        agent = AgentModel(id=agent_id, name="builtin-a", type="builtin", builtin_key="test_agent", config={})

        db.add(tenant)
        db.add(user)
        db.add(agent)
        await db.flush()
        db.add(TenantMembershipModel(tenant_id=tenant_id, user_id=user_id, role="owner", status="active"))
        await db.commit()

        principal = AuthPrincipal(user_id=user_id, role="admin", tenant_id=str(tenant_id), tenant_role="owner")
        ds = await create_eval_dataset(
            agent_id=str(agent_id),
            body=CreateDatasetRequest(name="dataset-run", description="d"),
            user=principal,
            db=db,
        )

        await import_eval_cases(
            agent_id=str(agent_id),
            dataset_id=ds["id"],
            body=ImportCasesRequest(
                cases=[
                    {
                        "input": {"messages": [{"role": "user", "content": "please pass"}]},
                        "expected_output": {"tool_calls": [{"name": "search", "arguments": {"q": "please pass"}}]},
                    },
                    {
                        "input": {"messages": [{"role": "user", "content": "please fail"}]},
                        "expected_output": {"tool_calls": [{"name": "search", "arguments": {"q": "please fail"}}]},
                    },
                ]
            ),
            user=principal,
            db=db,
        )

        run = await create_eval_run(
            agent_id=str(agent_id),
            body=CreateRunRequest(
                dataset_id=ds["id"],
                config={"evaluators": ["trajectory_match"], "trajectory_match_mode": "strict"},
            ),
            user=principal,
            db=db,
        )

        assert run["status"] == "completed"
        assert run["summary"]["total"] == 2
        assert run["summary"]["passed"] == 1
        assert run["summary"]["failed"] == 1
        assert run["summary"]["errors"] == 0
        assert run["summary"]["avg_score"] == pytest.approx(0.5)

        rows = (
            await db.execute(
                select(EvalResultModel).where(EvalResultModel.run_id == UUID(run["id"]))
            )
        ).scalars().all()
        assert len(rows) == 2
        statuses = sorted(r.status for r in rows)
        assert statuses == ["failed", "passed"]
