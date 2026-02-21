from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import UUID, uuid4
from ..db import get_db
from ..models.db_models import SessionModel, AgentModel
from ..core.auth import AuthPrincipal, get_current_user
from ..services.user_shadow_service import UserShadowService
from ..services.tenant_shadow_service import TenantShadowService
from agent_core.settings import get_settings

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _tenant_uuid(user: AuthPrincipal) -> UUID:
    tenant_id = user.tenant_id or get_settings().auth_default_tenant_id
    try:
        return UUID(str(tenant_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant context") from exc


async def _ensure_tenant_membership_or_403(db: AsyncSession, user: AuthPrincipal, tenant_id: UUID) -> None:
    tenant_service = TenantShadowService(db)
    if not await tenant_service.has_active_membership(tenant_id, user.user_id):
        raise HTTPException(status_code=403, detail="Tenant membership required")

@router.post("/", response_model=dict)
async def create_session(
    agent_id: Optional[str] = Body(None, embed=True),
    title: Optional[str] = Body(None, embed=True),
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new session for a specific agent."""
    tenant_id = _tenant_uuid(user)
    await UserShadowService(db).ensure_user(user.user_id, user.email, user.role)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
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
        tenant_id=tenant_id,
        user_id=user.user_id,
        agent_id=agent.id,
        title=title or "New Chat",
        thread_id=uuid4(),
        state={"owner_user_id": user.user_id}
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
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    res = await db.execute(
        select(SessionModel).where(
            SessionModel.id == session_id,
            SessionModel.tenant_id == tenant_id,
        )
    )
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    owner_user_id = session.user_id or ((session.state or {}).get("owner_user_id") if isinstance(session.state, dict) else None)
    if user.role != "admin" and owner_user_id and owner_user_id != user.user_id:
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
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all sessions, ordered by updated_at desc."""
    from sqlalchemy import desc

    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    stmt = (
        select(SessionModel)
        .where(SessionModel.tenant_id == tenant_id)
        .order_by(desc(SessionModel.updated_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    if user.role != "admin":
        sessions = [
            s for s in sessions
            if (s.user_id == user.user_id)
            or (isinstance(s.state, dict) and (s.state.get("owner_user_id") == user.user_id))
        ]
    
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
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a session."""
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    res = await db.execute(
        select(SessionModel).where(
            SessionModel.id == session_id,
            SessionModel.tenant_id == tenant_id,
        )
    )
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    owner_user_id = session.user_id or ((session.state or {}).get("owner_user_id") if isinstance(session.state, dict) else None)
    if user.role != "admin" and owner_user_id and owner_user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    
    await db.delete(session)
    await db.commit()
    return {"status": "deleted"}
