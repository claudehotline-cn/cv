import asyncio
from sqlalchemy import text
from app.db import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as session:
        print("Migrating audit_events table...")
        try:
            await session.execute(text("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS session_id VARCHAR(100)"))
            await session.execute(text("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS thread_id VARCHAR(100)"))
            await session.commit()
            print("Successfully added session_id and thread_id columns.")
        except Exception as e:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
