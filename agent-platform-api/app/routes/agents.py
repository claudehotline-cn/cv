from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from ..db import get_db
from ..models.db_models import AgentModel

router = APIRouter(prefix="/agents", tags=["agents"])

@router.get("/", response_model=List[dict])
async def list_agents(db: AsyncSession = Depends(get_db)):
    """List all available agents."""
    result = await db.execute(select(AgentModel))
    agents = result.scalars().all()
    # Simple serialization
    return [
        {
            "id": str(a.id),
            "name": a.name,
            "type": a.type,
            "builtin_key": a.builtin_key,
            "config": a.config
        }
        for a in agents
    ]

@router.get("/{agent_id}")
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentModel).where(AgentModel.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "id": str(agent.id),
        "name": agent.name,
        "type": agent.type,
        "builtin_key": agent.builtin_key,
        "config": agent.config
    }
