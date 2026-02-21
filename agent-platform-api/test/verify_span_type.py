

import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from tabulate import tabulate

DATABASE_URL = "postgresql+asyncpg://cv_kb:cv_kb_pass@pgvector:5432/cv_kb"

async def main():
    target_id = "b3af08d1-ebca-4a63-8ab4-492a56257088"
    print(f"Connecting to {DATABASE_URL}")
    engine = create_async_engine(DATABASE_URL)
    
    async with engine.connect() as conn:
        # Check Root Span
        print(f"Checking for Root Span {target_id}...")
        res = await conn.execute(text(f"SELECT * FROM agent_spans WHERE span_id = '{target_id}'"))
        root = res.fetchone()
        
        if root:
             print(f"✅ Root Span FOUND: {root}")
        else:
             print(f"❌ Root Span NOT FOUND: {target_id}")

        print("Fetching recent spans...")
        result = await conn.execute(text(
            "SELECT span_id, span_type, parent_span_id, status, started_at, node_name "
            "FROM agent_spans "
            "ORDER BY started_at DESC "
            "LIMIT 20"
        ))
        # ... rest of printing logic ...
        rows = result.fetchall()
        headers = ["span_id", "span_type", "parent_span_id", "status", "started_at", "node_name"]
        data = [[str(r[0])[:8], r[1], str(r[2])[:8] if r[2] else "None", r[3], r[4].strftime("%H:%M:%S") if r[4] else "N/A", r[5]] for r in rows]
        print(tabulate(data, headers=headers))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error: {e}")
