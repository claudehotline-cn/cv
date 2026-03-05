import pytest
from sqlalchemy import text

from app.db import AsyncSessionLocal, init_db


@pytest.mark.asyncio
async def test_phase2_tables_and_indexes_exist_after_init() -> None:
    await init_db()

    async with AsyncSessionLocal() as db:
        table_names = [
            "tenant_guardrail_policies",
            "guardrail_events",
            "semantic_cache_entries",
        ]
        for name in table_names:
            result = await db.execute(text("SELECT to_regclass(:name)"), {"name": name})
            assert result.scalar_one() == name

        index_names = [
            "idx_guardrail_events_tenant_id",
            "idx_guardrail_events_request_id",
            "idx_guardrail_events_created_at",
            "idx_semantic_cache_entries_lookup",
            "idx_semantic_cache_entries_embedding",
        ]
        for name in index_names:
            result = await db.execute(text("SELECT to_regclass(:name)"), {"name": name})
            assert result.scalar_one() == name

        ext = await db.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        assert ext.scalar_one() == "vector"

        col_type = await db.execute(
            text(
                """
                SELECT pg_catalog.format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute a
                JOIN pg_class c ON a.attrelid = c.oid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = 'semantic_cache_entries'
                  AND a.attname = 'embedding'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                """
            )
        )
        assert col_type.scalar_one() == "vector(1024)"
