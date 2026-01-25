import asyncio
from sqlalchemy import text
from app.db import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as session:
        res = await session.execute(text("SELECT event_type, run_id, span_id, payload FROM audit_events ORDER BY event_time DESC LIMIT 20"))
        events = res.fetchall()
        print(f"Found {len(events)} events:")
        for e in events:
            print(f"[{e[0]}] run={e[1]} span={e[2]} payload={str(e[3])[:100]}")

if __name__ == "__main__":
    asyncio.run(main())
