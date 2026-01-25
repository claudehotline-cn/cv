import asyncio
from sqlalchemy import select, update, text
from app.db import AsyncSessionLocal
from app.models.db_models import SessionModel
from uuid import uuid4

async def main():
    async with AsyncSessionLocal() as session:
        # Add column if not exists
        try:
            await session.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS thread_id UUID"))
            await session.commit()
            print("Verified/Added thread_id column.")
        except Exception as e:
            print(f"Column addition failed (might exist): {e}")

        # Find sessions with null thread_id
        stmt = select(SessionModel).where(SessionModel.thread_id.is_(None))
        res = await session.execute(stmt)
        sessions = res.scalars().all()
        
        print(f"Found {len(sessions)} sessions with null thread_id")
        
        count = 0
        for s in sessions:
            # Set thread_id to session.id (for migration compatibility)
            # Or generate new one. User said "thread_id != session_id".
            # But for OLD sessions, if we generate NEW thread_id, we lose checkpoint history 
            # (because LangGraph checkpoints were stored under thread_id=session_id previously??)
            # Before this change, thread_id WAS session_id.
            # So to preserve history, we MUST set thread_id = session_id for OLD sessions.
            # But for NEW sessions we generate distinct UUID.
            
            s.thread_id = s.id
            count += 1
            
        await session.commit()
        print(f"Backfilled {count} sessions.")
        
        # Verify
        ct = await session.execute(select(SessionModel).where(SessionModel.thread_id.is_(None)))
        print(f"Remaining nulls: {len(ct.scalars().all())}")

if __name__ == "__main__":
    asyncio.run(main())
