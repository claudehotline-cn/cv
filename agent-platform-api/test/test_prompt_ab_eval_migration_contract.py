import pytest
from sqlalchemy import text

from app.db import AsyncSessionLocal, init_db


@pytest.mark.asyncio
async def test_w3_tables_exist_after_init():
    await init_db()
    async with AsyncSessionLocal() as db:
        names = [
            "prompt_ab_tests",
            "eval_datasets",
            "eval_cases",
            "eval_runs",
            "eval_results",
        ]
        for n in names:
            r = await db.execute(text("SELECT to_regclass(:name)"), {"name": n})
            assert r.scalar_one() == n
