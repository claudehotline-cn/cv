from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from ..db import get_db
from ..models.db_models import SessionModel, AgentModel

router = APIRouter(prefix="/sessions", tags=["sessions"])

@router.post("/", response_model=dict)
async def create_session(
    agent_id: str = Body(..., embed=True),
    title: Optional[str] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db)
):
    """Create a new session for a specific agent."""
    # Validate agent
    agent_res = await db.execute(select(AgentModel).where(AgentModel.id == agent_id))
    agent = agent_res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    new_session = SessionModel(
        agent_id=agent.id,
        title=title or "New Chat"
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    
    return {
        "id": str(new_session.id),
        "agent_id": str(new_session.agent_id),
        "title": new_session.title,
        "created_at": new_session.created_at
    }

@router.get("/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "id": str(session.id),
        "agent_id": str(session.agent_id),
        "title": session.title,
        "created_at": session.created_at,
        "state": session.state
    }
