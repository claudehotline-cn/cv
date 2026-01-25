from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, String, func
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models.db_models import AgentRunModel, AuditEventModel, AgentSpanModel

router = APIRouter(prefix="/audit", tags=["audit"])

# --- View Models ---
class AuditRunSummary(BaseModel):
    run_id: str
    time: datetime
    root_agent_name: Optional[str]
    status: str
    duration_seconds: Optional[float]
    initiator: Optional[str]
    conversation_id: Optional[str]
    llm_calls_count: int = 0
    tool_calls_count: int = 0
    failures_count: int = 0

class PaginatedRunsResponse(BaseModel):
    items: List[AuditRunSummary]
    total: int
    limit: int
    offset: int

class AuditEventView(BaseModel):
    event_id: str
    time: datetime
    type: str
    component: Optional[str]
    message: str
    severity: str
    payload: Optional[Dict[str, Any]]
    span_id: Optional[str] = None

class RunDetailView(BaseModel):
    run: AuditRunSummary
    failures: List[AuditEventView]
    spans: List[Dict[str, Any]] # simplified span view
    recent_events: List[AuditEventView]

# ... (Endpoints) ...
# Inside get_run_summary

@router.get("/runs", response_model=PaginatedRunsResponse)
async def list_runs(
    limit: int = 50, 
    offset: int = 0,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    q: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db)
):
    """List agent runs with summary statistics."""
    # Build base query
    stmt = select(AgentRunModel)
    
    if status:
        stmt = stmt.where(AgentRunModel.status == status)
    if agent:
        stmt = stmt.where(AgentRunModel.root_agent_name == agent)
    
    if q:
        # Search ID or User or Conversation
        from sqlalchemy import or_
        stmt = stmt.where(or_(
            AgentRunModel.run_id.cast(String).ilike(f"%{q}%"),
            AgentRunModel.conversation_id.ilike(f"%{q}%"),
            AgentRunModel.initiator_id.ilike(f"%{q}%")
        ))
        
    if start_date:
        stmt = stmt.where(AgentRunModel.started_at >= start_date)
    if end_date:
        stmt = stmt.where(AgentRunModel.started_at <= end_date)

    # Get Total Count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_res = await db.execute(count_stmt)
    total = total_res.scalar_one()
        
    # Apply Limit/Offset
    stmt = stmt.order_by(desc(AgentRunModel.started_at)).limit(limit).offset(offset)
    result = await db.execute(stmt)
    runs = result.scalars().all()
    
    output = []
    for r in runs:
        # Calculate duration
        duration = None
        if r.ended_at and r.started_at:
            duration = (r.ended_at - r.started_at).total_seconds()
            
        output.append(AuditRunSummary(
            run_id=str(r.run_id),
            time=r.started_at,
            root_agent_name=r.root_agent_name or "Unknown Agent",
            status=r.status,
            duration_seconds=duration,
            initiator=r.initiator_id or "System",
            conversation_id=r.conversation_id,
            llm_calls_count=0, # TODO: Add aggregation
            tool_calls_count=0,
            failures_count=0
        ))
        
    return PaginatedRunsResponse(
        items=output,
        total=total,
        limit=limit,
        offset=offset
    )

@router.get("/runs/{run_id}/summary", response_model=RunDetailView)
async def get_run_summary(
    run_id: str, 
    db: AsyncSession = Depends(get_db)
):
    """Get detailed summary for a specific run (Failures, Spans, Events)."""
    # 1. Get Run
    run_res = await db.execute(select(AgentRunModel).where(AgentRunModel.run_id == UUID(run_id)))
    run = run_res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
        
    # 2. Get Events (Recent 200)
    events_res = await db.execute(
        select(AuditEventModel)
        .where(AuditEventModel.run_id == UUID(run_id))
        .order_by(AuditEventModel.event_time) # Chronological
        .limit(200)
    )
    events = events_res.scalars().all()
    
    # 3. Process Events into View Models
    failures = []
    event_views = []
    
    llm_count = 0
    tool_count = 0
    span_names = {}
    
    for e in events:
        severity = "Info"
        if "error" in e.event_type or "failed" in e.event_type:
            severity = "Error"
        elif "start" in e.event_type:
            severity = "Info"
        elif "end" in e.event_type:
            severity = "Success"
            
        # Infer Span Name from Payload
        if e.span_id:
            sid = str(e.span_id)
            if e.payload:
                if "model" in e.payload:
                    span_names[sid] = f"LLM: {e.payload['model']}"
                elif "tool_name" in e.payload:
                    span_names[sid] = f"Tool: {e.payload['tool_name']}"

        # Construct message from payload or type
        msg = e.event_type
        if e.payload:
            if "error_message" in e.payload:
                msg = e.payload["error_message"]
            elif "tool_name" in e.payload:
                msg = f"Tool: {e.payload['tool_name']}"
            elif "model" in e.payload:
                msg = f"Model: {e.payload['model']}"
        
        view = AuditEventView(
            event_id=str(e.event_id),
            time=e.event_time,
            type=e.event_type,
            component=e.component,
            message=msg,
            severity=severity,
            payload=e.payload,
            span_id=str(e.span_id) if e.span_id else None
        )
        event_views.append(view)
        
        if severity == "Error":
            failures.append(view)
        if e.event_type == "llm_called": llm_count += 1
        if e.event_type == "tool_call_executed": tool_count += 1

    # 4. Get Spans (Optional, simplistic list for now)
    spans_res = await db.execute(
        select(AgentSpanModel)
        .where(AgentSpanModel.run_id == UUID(run_id))
        .order_by(AgentSpanModel.started_at)
    )
    db_spans = spans_res.scalars().all()
    spans = []
    for s in db_spans:
        sid = str(s.span_id)
        name = s.node_name or s.agent_name or "Unknown"

        # Refine Name
        if sid in span_names:
            name = span_names[sid]
        elif not s.parent_span_id and run.root_agent_name:
            name = run.root_agent_name
        elif name.lower() in ["agent", "chain", "tool", "llm"]:
             name = name.upper() if name.lower() == "llm" else name.capitalize()

        spans.append({
            "span_id": sid,
            "parent_span_id": str(s.parent_span_id) if s.parent_span_id else None,
            "type": s.span_type,
            "name": name,
            "status": s.status,
            "duration": (s.ended_at - s.started_at).total_seconds() if s.ended_at else None
        })

    # Summary Object
    duration = (run.ended_at - run.started_at).total_seconds() if run.ended_at else None
    summary = AuditRunSummary(
        run_id=str(run.run_id),
        time=run.started_at,
        root_agent_name=run.root_agent_name,
        status=run.status,
        duration_seconds=duration,
        initiator=run.initiator_id,
        conversation_id=run.conversation_id,
        llm_calls_count=llm_count,
        tool_calls_count=tool_count,
        failures_count=len(failures)
    )
    
    return RunDetailView(
        run=summary,
        failures=failures,
        spans=spans,
        recent_events=event_views
    )
