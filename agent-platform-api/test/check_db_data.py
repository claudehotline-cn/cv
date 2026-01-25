import asyncio
from sqlalchemy import text
from app.db import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        # Check latest audit event to confirm IDs
        res = await db.execute(text("SELECT run_id, thread_id, session_id FROM audit_events ORDER BY event_time DESC LIMIT 1"))
        row = res.fetchone()
        if row:
            print(f"Run ID: {row[0]}, Thread ID: {row[1]}, Session ID: {row[2]}")
        else:
            print("No audit events found.")
        
        res_runs_count = await db.execute(text("SELECT count(*) FROM agent_runs"))
        count_runs = res_runs_count.scalar()
        
        res_events = await db.execute(text("SELECT count(*) FROM audit_events"))
        count_events = res_events.scalar()

        res_spans = await db.execute(text("SELECT count(*) FROM agent_spans"))
        count_spans = res_spans.scalar()

        res_tools = await db.execute(text("SELECT count(*) FROM tool_audits"))
        count_tools = res_tools.scalar()

        res_approvals = await db.execute(text("SELECT count(*) FROM approval_requests"))
        count_approvals = res_approvals.scalar()

        res_blobs = await db.execute(text("SELECT count(*) FROM audit_blobs"))
        count_blobs = res_blobs.scalar()
        
        print(f"Agent Runs: {count_runs}")
        print(f"Audit Events: {count_events}")
        print(f"Agent Spans: {count_spans}")
        print(f"Tool Audits: {count_tools}")
        print(f"Approval Requests: {count_approvals}")
        print(f"Audit Blobs: {count_blobs}")
        
        if count_runs == 0 and count_events > 0:
            print("WARNING: Events exist but Runs do not. Foreign Key issue?")

if __name__ == "__main__":
    asyncio.run(main())
