import asyncio
import uuid
import sys
import os

# Add /app to path so we can import app modules
sys.path.append("/app")

from app.services.audit_service import AuditPersistenceService
from app.db import AsyncSessionLocal
from app.models.db_models import AgentSpanModel, AgentRunModel

async def test():
    run_id = uuid.uuid4()
    span_id = uuid.uuid4()
    session_id = str(uuid.uuid4())
    print(f"Testing Run ID: {run_id}")

    try:
        async with AsyncSessionLocal() as session:
            service = AuditPersistenceService(session)

            # 1. Start Run
            print("Event: run_started")
            await service.process_event({
                "event_id": str(uuid.uuid4()),
                "event_type": "run_started",
                "run_id": str(run_id),
                "session_id": session_id,
                "payload_json": "{}"
            })

            # 2. Start Span
            print("Event: chain_start")
            await service.process_event({
                "event_id": str(uuid.uuid4()),
                "event_type": "chain_start",
                "run_id": str(run_id),
                "span_id": str(span_id),
                "session_id": session_id,
                "payload_json": "{\"name\": \"test_node\"}"
            })

            # 3. Interrupt Span
            print("Event: chain_interrupted")
            await service.process_event({
                "event_id": str(uuid.uuid4()),
                "event_type": "chain_interrupted",  # <--- The new event type
                "run_id": str(run_id),
                "span_id": str(span_id),
                "session_id": session_id,
                "payload_json": "{}"
            })
            
            # 4. Interrupt Run
            print("Event: run_interrupted")
            await service.process_event({
                 "event_id": str(uuid.uuid4()),
                 "event_type": "run_interrupted", # <--- The new event type
                 "run_id": str(run_id),
                 "session_id": session_id,
                 "payload_json": "{}"
            })

        # Verify
        async with AsyncSessionLocal() as session:
            span = await session.get(AgentSpanModel, span_id)
            run = await session.get(AgentRunModel, run_id)
            
            print("-" * 30)
            print(f"Span Status: {span.status}")
            print(f"Run Status: {run.status}")
            print("-" * 30)
            
            if span.status == "interrupted" and run.status == "interrupted":
                print("SUCCESS: Status updated to 'interrupted'")
            else:
                print(f"FAILURE: Expected 'interrupted', got Span={span.status}, Run={run.status}")
                sys.exit(1)

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test())
