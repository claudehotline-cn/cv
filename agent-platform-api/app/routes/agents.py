from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from ..db import get_db
from ..models.db_models import AgentModel, AgentVersionModel
from ..core.auth import AuthPrincipal, get_current_user, require_admin

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

async def _version_summary(version_id, db: AsyncSession) -> Optional[dict]:
    if not version_id:
        return None
    ver = await db.get(AgentVersionModel, version_id)
    if not ver:
        return None
    return {
        "version": ver.version,
        "status": ver.status,
        "published_at": ver.published_at.isoformat() if ver.published_at else None,
    }


@router.get("/", response_model=List[dict])
async def list_agents(
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all available agents."""
    result = await db.execute(select(AgentModel).order_by(AgentModel.created_at.desc()))
    agents = result.scalars().all()
    items = []
    for a in agents:
        items.append({
            "id": str(a.id),
            "name": a.name,
            "type": a.type,
            "builtin_key": a.builtin_key,
            "config": a.config,
            "published_version": await _version_summary(a.published_version_id, db),
            "draft_version": await _version_summary(a.draft_version_id, db),
        })
    return items

@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AgentModel).where(AgentModel.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "id": str(agent.id),
        "name": agent.name,
        "type": agent.type,
        "builtin_key": agent.builtin_key,
        "config": agent.config,
        "published_version": await _version_summary(agent.published_version_id, db),
        "draft_version": await _version_summary(agent.draft_version_id, db),
    }

@router.post("/")
async def create_agent(
    agent: AgentCreate,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
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
async def update_agent(
    agent_id: str,
    update: AgentUpdate,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a custom agent. Creates/updates a draft version."""
    result = await db.execute(select(AgentModel).where(AgentModel.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.type == "builtin":
        raise HTTPException(status_code=400, detail="Cannot update built-in agents")

    # Build new config
    config = dict(agent.config or {})
    if update.description is not None:
        config["description"] = update.description
    if update.system_prompt is not None:
        config["system_prompt"] = update.system_prompt
    if update.model is not None:
        config["model"] = update.model
    if update.temperature is not None:
        config["temperature"] = update.temperature

    # Update agent name
    if update.name is not None:
        agent.name = update.name

    # Create or update draft version
    if agent.draft_version_id:
        draft = await db.get(AgentVersionModel, agent.draft_version_id)
        if draft and draft.status == "draft":
            draft.config = config
        else:
            # Draft pointer stale, create new
            max_ver = await db.execute(
                select(func.coalesce(func.max(AgentVersionModel.version), 0))
                .where(AgentVersionModel.agent_id == agent.id)
            )
            next_ver = max_ver.scalar() + 1
            draft = AgentVersionModel(
                agent_id=agent.id, version=next_ver, status="draft",
                config=config, created_by=user.user_id,
            )
            db.add(draft)
            await db.flush()
            agent.draft_version_id = draft.id
    else:
        max_ver = await db.execute(
            select(func.coalesce(func.max(AgentVersionModel.version), 0))
            .where(AgentVersionModel.agent_id == agent.id)
        )
        next_ver = max_ver.scalar() + 1
        draft = AgentVersionModel(
            agent_id=agent.id, version=next_ver, status="draft",
            config=config, created_by=user.user_id,
        )
        db.add(draft)
        await db.flush()
        agent.draft_version_id = draft.id

    agent.config = config
    await db.commit()
    await db.refresh(agent)

    return {
        "id": str(agent.id),
        "name": agent.name,
        "type": agent.type,
        "config": agent.config,
        "published_version": await _version_summary(agent.published_version_id, db),
        "draft_version": await _version_summary(agent.draft_version_id, db),
    }

@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
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
