
import asyncio
from sqlalchemy import text
from app.db import AsyncSessionLocal
import sys

async def main():
    try:
        async with AsyncSessionLocal() as db:
            print("--- Tool Audit Check ---")
            res = await db.execute(text("SELECT tool_name, session_id, thread_id FROM tool_audits ORDER BY request_time DESC LIMIT 5"))
            rows = res.fetchall()
            print(f"Found {len(rows)} rows.")
            for row in rows:
                print(f"Name: {row[0]}, Sess: {row[1]}, Thread: {row[2]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
