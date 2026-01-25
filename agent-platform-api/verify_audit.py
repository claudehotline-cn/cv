
import asyncio
import logging
from uuid import uuid4
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)

# Mock config
import os
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/agent_platform" # Adjust if needed, but usually this is the default in this env? 
# Actually context says user has workspaces. I should check env vars or config.py.
# But `app.db` uses `get_settings`.

from app.db import init_db, AsyncSessionLocal
from app.services.audit_service import AuditPersistenceService
from app.models.db_models import AgentRunModel

async def verify():
    print("--- 1. Initialize DB (Create Tables) ---")
    await init_db()
    
    print("--- 2. Simulate Events ---")
    run_id = str(uuid4())
    span_id = str(uuid4())
    
    events = [
        {
            "event_id": str(uuid4()),
            "event_type": "run_started",
            "run_id": run_id,
            "component": "agent",
            "payload_json": '{"inputs": "Hello"}'
        },
        {
            "event_id": str(uuid4()),
            "event_type": "tool_call_requested",
            "run_id": run_id,
            "span_id": span_id,
            "component": "tool",
            "payload_json": '{"tool_name": "search", "input": "query"}'
        },
        {
            "event_id": str(uuid4()),
            "event_type": "run_finished",
            "run_id": run_id,
            "component": "agent",
            "payload_json": '{"outputs": "Hi"}'
        }
    ]
    
    async with AsyncSessionLocal() as db:
        service = AuditPersistenceService(db)
        for evt in events:
            print(f"Processing {evt['event_type']}...")
            await service.process_event(evt)
            
    print("--- 3. Verify DB Content ---")
    async with AsyncSessionLocal() as db:
        run = await db.get(AgentRunModel, run_id)
        if run:
            print(f"PASS: Run found! ID={run.run_id}, Status={run.status}")
        else:
            print("FAIL: Run not found!")
            
if __name__ == "__main__":
    asyncio.run(verify())
