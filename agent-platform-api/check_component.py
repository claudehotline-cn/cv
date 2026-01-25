
import asyncio
from sqlalchemy import text
from app.db import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT event_type, component FROM audit_events LIMIT 1"))
        row = res.fetchone()
        if row:
            print(f"Event Type: {row[0]}, Component: {row[1]}")
        else:
            print("No events found.")

if __name__ == "__main__":
    asyncio.run(main())
