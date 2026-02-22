import pytest
from uuid import uuid4

from app.db import AsyncSessionLocal, init_db
from app.routes.prompts import create_ab_test, complete_ab_test, PromptABTestCreate, PromptABTestComplete
from app.models.db_models import PromptTemplateModel, PromptVersionModel


class _User:
    def __init__(self, user_id: str):
        self.user_id = user_id


@pytest.mark.asyncio
async def test_prompt_ab_api_create_and_complete_publishes_winner():
    await init_db()

    async with AsyncSessionLocal() as db:
        tmpl = PromptTemplateModel(
            tenant_id=None,
            key=f"test.prompt.api.{uuid4()}",
            name="ab api test",
            category="system",
        )
        db.add(tmpl)
        await db.flush()

        base = PromptVersionModel(template_id=tmpl.id, version=1, status="published", content="base")
        va = PromptVersionModel(template_id=tmpl.id, version=2, status="draft", content="A")
        vb = PromptVersionModel(template_id=tmpl.id, version=3, status="draft", content="B")
        db.add_all([base, va, vb])
        await db.flush()
        tmpl.published_version_id = base.id
        await db.commit()

        created = await create_ab_test(
            template_id=str(tmpl.id),
            body=PromptABTestCreate(
                name="exp-1",
                variant_a_version=2,
                variant_b_version=3,
                traffic_split=0.5,
            ),
            _=_User("admin"),
            db=db,
        )
        assert created["status"] == "running"

        completed = await complete_ab_test(
            template_id=str(tmpl.id),
            test_id=created["id"],
            body=PromptABTestComplete(winner_version=2),
            _=_User("admin"),
            db=db,
        )
        assert completed["status"] == "completed"
        assert completed["winner_version_id"] == str(va.id)

        await db.refresh(tmpl)
        assert str(tmpl.published_version_id) == str(va.id)
