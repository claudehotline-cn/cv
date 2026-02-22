import pytest
from uuid import uuid4

from app.core.auth import AuthPrincipal
from app.db import AsyncSessionLocal, init_db
from sqlalchemy import select

from app.models.db_models import AgentModel, EvalDatasetModel, PlatformUserModel, TenantMembershipModel, TenantModel
from app.routes.eval import create_eval_dataset, CreateDatasetRequest


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
