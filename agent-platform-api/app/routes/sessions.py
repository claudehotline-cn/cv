from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import uuid4
from ..db import get_db
from ..models.db_models import SessionModel, AgentModel
from ..core.auth import AuthPrincipal, get_current_user

router = APIRouter(prefix="/sessions", tags=["sessions"])

@router.post("/", response_model=dict)
async def create_session(
    agent_id: Optional[str] = Body(None, embed=True),
    title: Optional[str] = Body(None, embed=True),
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new session for a specific agent."""
    # If no agent_id provided, use data_agent as default
    if not agent_id:
        result = await db.execute(select(AgentModel).where(AgentModel.builtin_key == "data_agent"))
        agent = result.scalar_one_or_none()
        if not agent:
            # Fallback to first available agent
            result = await db.execute(select(AgentModel).limit(1))
            agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=400, detail="No agents available. Please create an agent first.")
    else:
        # Validate agent
        agent_res = await db.execute(select(AgentModel).where(AgentModel.id == agent_id))
        agent = agent_res.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

    new_session = SessionModel(
        agent_id=agent.id,
        title=title or "New Chat",
        thread_id=uuid4()
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
async def get_session(
    session_id: str,
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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


@router.get("/")
async def list_sessions(
    limit: int = 50,
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all sessions, ordered by updated_at desc."""
    from sqlalchemy import desc
    
    stmt = select(SessionModel).order_by(desc(SessionModel.updated_at)).limit(limit)
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    
    return {
        "sessions": [
            {
                "id": str(s.id),
                "agent_id": str(s.agent_id),
                "title": s.title,
                "createdAt": s.created_at,
                "updatedAt": s.updated_at
            }
            for s in sessions
        ]
    }


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a session."""
    res = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    await db.delete(session)
    await db.commit()
    return {"status": "deleted"}
