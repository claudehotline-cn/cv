import pytest
from uuid import uuid4

from app.db import AsyncSessionLocal, init_db
from app.core.prompt_resolver import PromptResolver
from app.models.db_models import PromptTemplateModel, PromptVersionModel, PromptABTestModel


@pytest.mark.asyncio
async def test_prompt_resolver_uses_ab_variant_when_test_specified():
    await init_db()
    key = f"test.prompt.ab.{uuid4()}"

    async with AsyncSessionLocal() as db:
        tmpl = PromptTemplateModel(
            tenant_id=None,
            key=key,
            name="ab test prompt",
            category="system",
        )
        db.add(tmpl)
        await db.flush()

        published = PromptVersionModel(
            template_id=tmpl.id,
            version=1,
            status="published",
            content="published-content",
        )
        var_a = PromptVersionModel(
            template_id=tmpl.id,
            version=2,
            status="draft",
            content="variant-a-content",
        )
        var_b = PromptVersionModel(
            template_id=tmpl.id,
            version=3,
            status="draft",
            content="variant-b-content",
        )
        db.add_all([published, var_a, var_b])
        await db.flush()

        tmpl.published_version_id = published.id

        ab = PromptABTestModel(
            template_id=tmpl.id,
            name="ab-1",
            status="running",
            variant_a_id=var_a.id,
            variant_b_id=var_b.id,
            traffic_split=1.0,
        )
        db.add(ab)
        await db.commit()

    async with AsyncSessionLocal() as db:
        rendered = await PromptResolver.resolve(
            db=db,
            tenant_id=None,
            key=key,
            ab_test_id=str(ab.id),
            user_id="user-1",
        )
        assert rendered == "variant-a-content"
