
import asyncio
from sqlalchemy import text
from app.db import AsyncSessionLocal

async def migrate():
    async with AsyncSessionLocal() as db:
        print("Migrating tool_audits table...")
        await db.execute(text("ALTER TABLE tool_audits ADD COLUMN IF NOT EXISTS session_id VARCHAR(100)"))
        await db.execute(text("ALTER TABLE tool_audits ADD COLUMN IF NOT EXISTS thread_id VARCHAR(100)"))
        await db.commit()
        print("Migration done.")

if __name__ == "__main__":
    asyncio.run(migrate())
