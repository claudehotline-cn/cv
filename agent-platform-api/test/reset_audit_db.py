
import asyncio
from sqlalchemy import text
from app.db import AsyncSessionLocal, engine
from app.models.db_models import Base

async def main():
    async with engine.begin() as conn:
        print("Dropping audit tables...")
        # Drop dependent tables first
        await conn.execute(text("DROP TABLE IF EXISTS tool_audits CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS audit_events CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_spans CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_runs CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS approval_decisions CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS approval_requests CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS audit_blobs CASCADE"))
        
        print("Recreating tables...")
        await conn.run_sync(Base.metadata.create_all)
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
