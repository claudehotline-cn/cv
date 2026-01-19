from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from ..db import get_db
from ..models.db_models import AgentModel

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    model: str = "gpt-4o"
    temperature: float = 0.7

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None

@router.get("/", response_model=List[dict])
async def list_agents(db: AsyncSession = Depends(get_db)):
    """List all available agents."""
    result = await db.execute(select(AgentModel).order_by(AgentModel.created_at.desc()))
    agents = result.scalars().all()
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

@router.post("/")
async def create_agent(agent: AgentCreate, db: AsyncSession = Depends(get_db)):
    """Create a new custom agent."""
    config = {
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "model": agent.model,
        "temperature": agent.temperature
    }
    
    new_agent = AgentModel(
        name=agent.name,
        type="custom",
        config=config
    )
    db.add(new_agent)
    await db.commit()
    await db.refresh(new_agent)
    
    return {
        "id": str(new_agent.id),
        "name": new_agent.name,
        "type": new_agent.type,
        "config": new_agent.config
    }

@router.put("/{agent_id}")
async def update_agent(agent_id: str, update: AgentUpdate, db: AsyncSession = Depends(get_db)):
    """Update a custom agent."""
    result = await db.execute(select(AgentModel).where(AgentModel.id == agent_id))
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    if agent.type == "builtin":
        raise HTTPException(status_code=400, detail="Cannot update built-in agents")

    # Update config fields
    config = dict(agent.config or {})
    if update.description is not None:
        config["description"] = update.description
    if update.system_prompt is not None:
        config["system_prompt"] = update.system_prompt
    if update.model is not None:
        config["model"] = update.model
    if update.temperature is not None:
        config["temperature"] = update.temperature
    
    # Update agent fields
    if update.name is not None:
        agent.name = update.name
    
    agent.config = config
    await db.commit()
    await db.refresh(agent)
    
    return {
        "id": str(agent.id),
        "name": agent.name,
        "type": agent.type,
        "config": agent.config
    }

@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a custom agent."""
    result = await db.execute(select(AgentModel).where(AgentModel.id == agent_id))
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    if agent.type == "builtin":
        raise HTTPException(status_code=400, detail="Cannot delete built-in agents")
        
    await db.delete(agent)
    await db.commit()
    return {"status": "success"}
