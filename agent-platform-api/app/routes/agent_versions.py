from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.db_models import AgentModel, AgentVersionModel
from ..core.auth import AuthPrincipal, get_current_user, require_admin

router = APIRouter(prefix="/agents/{agent_id}/versions", tags=["agent-versions"])


# --- Pydantic models (inline, following project convention) ---

class CreateDraftRequest(BaseModel):
    config: Dict[str, Any]
    change_summary: Optional[str] = None
    base_version: Optional[int] = None


class UpdateDraftRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None
    change_summary: Optional[str] = None


# --- Helpers ---

async def _get_agent_or_404(agent_id: str, db: AsyncSession) -> AgentModel:
    result = await db.execute(select(AgentModel).where(AgentModel.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _get_version_or_404(
    agent_id: str, version: int, db: AsyncSession
) -> AgentVersionModel:
    result = await db.execute(
        select(AgentVersionModel).where(
            AgentVersionModel.agent_id == agent_id,
            AgentVersionModel.version == version,
        )
    )
    ver = result.scalar_one_or_none()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")
    return ver


def _version_dict(v: AgentVersionModel) -> dict:
    return {
        "id": str(v.id),
        "agent_id": str(v.agent_id),
        "version": v.version,
        "status": v.status,
        "config": v.config,
        "change_summary": v.change_summary,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "published_at": v.published_at.isoformat() if v.published_at else None,
    }


async def _next_version(agent_id: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(AgentVersionModel.version), 0))
        .where(AgentVersionModel.agent_id == agent_id)
    )
    return result.scalar() + 1


# --- 1. List versions ---

@router.get("/")
async def list_versions(
    agent_id: str,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_agent_or_404(agent_id, db)
    stmt = (
        select(AgentVersionModel)
        .where(AgentVersionModel.agent_id == agent_id)
    )
    if status:
        stmt = stmt.where(AgentVersionModel.status == status)
    stmt = stmt.order_by(AgentVersionModel.version.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    versions = result.scalars().all()
    return [_version_dict(v) for v in versions]


# --- 2. Get version detail ---

@router.get("/{version}")
async def get_version(
    agent_id: str,
    version: int,
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_agent_or_404(agent_id, db)
    ver = await _get_version_or_404(agent_id, version, db)
    return _version_dict(ver)


# --- 3. Create new draft ---

@router.post("/")
async def create_draft(
    agent_id: str,
    body: CreateDraftRequest,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, db)

    # If base_version specified, copy its config as starting point
    if body.base_version is not None:
        base = await _get_version_or_404(agent_id, body.base_version, db)
        config = {**base.config, **body.config} if body.config else dict(base.config)
    else:
        config = body.config

    next_ver = await _next_version(agent_id, db)
    ver = AgentVersionModel(
        agent_id=agent.id,
        version=next_ver,
        status="draft",
        config=config,
        change_summary=body.change_summary,
        created_by=user.user_id,
    )
    db.add(ver)
    await db.flush()
    agent.draft_version_id = ver.id
    await db.commit()
    await db.refresh(ver)
    return _version_dict(ver)


# --- 4. Update draft ---

@router.put("/{version}")
async def update_draft(
    agent_id: str,
    version: int,
    body: UpdateDraftRequest,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _get_agent_or_404(agent_id, db)
    ver = await _get_version_or_404(agent_id, version, db)
    if ver.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft versions can be edited")
    if body.config is not None:
        ver.config = body.config
    if body.change_summary is not None:
        ver.change_summary = body.change_summary
    await db.commit()
    await db.refresh(ver)
    return _version_dict(ver)


# --- 5. Publish draft ---

@router.post("/{version}/publish")
async def publish_version(
    agent_id: str,
    version: int,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, db)
    ver = await _get_version_or_404(agent_id, version, db)
    if ver.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft versions can be published")

    # Archive current published version
    if agent.published_version_id:
        old_pub = await db.get(AgentVersionModel, agent.published_version_id)
        if old_pub and old_pub.status == "published":
            old_pub.status = "archived"

    ver.status = "published"
    ver.published_at = datetime.now(timezone.utc)
    agent.published_version_id = ver.id
    agent.config = ver.config
    # Clear draft pointer if it was this version
    if agent.draft_version_id == ver.id:
        agent.draft_version_id = None
    await db.commit()
    await db.refresh(ver)
    return _version_dict(ver)


# --- 6. Rollback (create new draft from historical version) ---

@router.post("/{version}/rollback")
async def rollback_version(
    agent_id: str,
    version: int,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, db)
    source = await _get_version_or_404(agent_id, version, db)

    next_ver = await _next_version(agent_id, db)
    ver = AgentVersionModel(
        agent_id=agent.id,
        version=next_ver,
        status="draft",
        config=dict(source.config),
        change_summary=f"Rollback from v{source.version}",
        created_by=user.user_id,
    )
    db.add(ver)
    await db.flush()
    agent.draft_version_id = ver.id
    await db.commit()
    await db.refresh(ver)
    return _version_dict(ver)


# --- 7. Diff two versions ---

@router.get("/{v1}/diff/{v2}")
async def diff_versions(
    agent_id: str,
    v1: int,
    v2: int,
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_agent_or_404(agent_id, db)
    ver1 = await _get_version_or_404(agent_id, v1, db)
    ver2 = await _get_version_or_404(agent_id, v2, db)

    from deepdiff import DeepDiff
    diff = DeepDiff(ver1.config, ver2.config, ignore_order=True)
    return {
        "v1": v1,
        "v2": v2,
        "diff": diff.to_dict(),
    }
