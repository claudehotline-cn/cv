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
    request_id: str
    time: datetime
    root_agent_name: Optional[str]
    status: str
    duration_seconds: Optional[float]
    initiator: Optional[str]
    conversation_id: Optional[str]
    session_id: Optional[str]
    llm_calls_count: int = 0
    tool_calls_count: int = 0
    failures_count: int = 0
    interrupts_count: int = 0

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
    spans: List[Dict[str, Any]]
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
            AgentRunModel.request_id.cast(String).ilike(f"%{q}%"),
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
    
    # Aggregation
    run_ids = [r.request_id for r in runs]
    stats = {rid: {"llm": 0, "tool": 0, "fail": 0, "interrupt": 0} for rid in run_ids}
    
    if run_ids:
        from sqlalchemy import or_
        # 1. Events Counts
        evt_stmt = (
            select(AuditEventModel.request_id, AuditEventModel.event_type, AuditEventModel.severity, func.count())
            .where(AuditEventModel.request_id.in_(run_ids))
            .where(or_(
                AuditEventModel.event_type.in_(['llm_called', 'tool_call_executed']),
                AuditEventModel.severity == 'Error'
            ))
            .group_by(AuditEventModel.request_id, AuditEventModel.event_type, AuditEventModel.severity)
        )
        evt_res = await db.execute(evt_stmt)
        for rid, etype, sev, cnt in evt_res:
            if rid in stats:
                if etype == 'llm_called': stats[rid]['llm'] += cnt
                if etype == 'tool_call_executed': stats[rid]['tool'] += cnt
                if sev == 'Error': stats[rid]['fail'] += cnt
                
        # 2. Interrupts (ApprovalRequests)
        from app.models.db_models import ApprovalRequestModel
        appr_stmt = (
            select(ApprovalRequestModel.request_id, func.count())
            .where(ApprovalRequestModel.request_id.in_(run_ids))
            .group_by(ApprovalRequestModel.request_id)
        )
        appr_res = await db.execute(appr_stmt)
        for rid, cnt in appr_res:
             if rid in stats:
                 stats[rid]['interrupt'] += cnt

    output = []
    for r in runs:
        # Calculate duration
        duration = None
        if r.ended_at and r.started_at:
            duration = (r.ended_at - r.started_at).total_seconds()
        
        s = stats.get(r.request_id, {})
        output.append(AuditRunSummary(
            request_id=str(r.request_id),
            time=r.started_at,
            root_agent_name=r.root_agent_name or "Unknown Agent",
            status=r.status,
            duration_seconds=duration,
            initiator=r.initiator_id or "System",
            conversation_id=r.conversation_id,
            session_id=r.conversation_id,
            llm_calls_count=s.get("llm", 0),
            tool_calls_count=s.get("tool", 0),
            failures_count=s.get("fail", 0),
            interrupts_count=s.get("interrupt", 0)
        ))
        
    return PaginatedRunsResponse(
        items=output,
        total=total,
        limit=limit,
        offset=offset
    )

@router.get("/runs/{request_id}/summary", response_model=RunDetailView)
async def get_run_summary(
    request_id: str, 
    db: AsyncSession = Depends(get_db)
):
    """Get detailed summary for a specific run (Failures, Spans, Events)."""
    # 1. Get Run
    if request_id == "latest":
        stmt = select(AgentRunModel).order_by(desc(AgentRunModel.started_at)).limit(1)
        run_res = await db.execute(stmt)
        run = run_res.scalar_one_or_none()
    else:
        try:
            uuid_obj = UUID(request_id)
            run_res = await db.execute(select(AgentRunModel).where(AgentRunModel.request_id == uuid_obj))
            run = run_res.scalar_one_or_none()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid UUID format")
            
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
        
    # Resolve actual ID for subsequent queries if we fetched 'latest'
    real_request_id = run.request_id
        
    # 2. Get Events (Recent 200)
    events_res = await db.execute(
        select(AuditEventModel)
        .where(AuditEventModel.request_id == real_request_id)
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
        is_interrupt = False

        if "interrupted" in e.event_type:
             severity = "Interrupt"
             is_interrupt = True
        elif "error" in e.event_type or "failed" in e.event_type:
            # Check for legacy GraphInterrupt stored as error
            if e.payload and e.payload.get("error_class") in ["GraphInterrupt", "NodeInterrupt"]:
                 severity = "Interrupt"
                 is_interrupt = True
            else:
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
            elif "langgraph_node" in e.payload:
                node = e.payload["langgraph_node"]
                if "start" in e.event_type:
                    msg = f"Node '{node}' started"
                elif "end" in e.event_type or "finished" in e.event_type:
                    msg = f"Node '{node}' finished"
                else:
                    msg = f"Node: {node}"
            elif "name" in e.payload:
                name = e.payload["name"]
                if "start" in e.event_type:
                    msg = f"Start: {name}"
                elif "end" in e.event_type or "finished" in e.event_type:
                     msg = f"End: {name}"
                else:
                     msg = f"{name}"
        
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

    # 3b. Get Pending Approvals for Status Enrichment
    from app.models.db_models import ApprovalRequestModel
    pending_stmt = select(ApprovalRequestModel).where(
        ApprovalRequestModel.request_id == real_request_id,
        ApprovalRequestModel.status == 'pending'
    )
    pending_res = await db.execute(pending_stmt)
    pending_reqs = pending_res.scalars().all()
    pending_map = {str(r.span_id): r for r in pending_reqs if r.span_id}

    # 4. Get Spans (Optional, simplistic list for now)
    spans_res = await db.execute(
        select(AgentSpanModel)
        .where(AgentSpanModel.request_id == real_request_id)
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
             
        # Prepend SubAgent Context to generic "Tools"
        if name == "Tools" and s.subagent_kind:
            clean_sub = s.subagent_kind.replace("_", " ").title()
            name = f"{clean_sub} Tools"
             
        # Context Enrichment
        if sid in pending_map:
             name += " (Waiting for Approval)"
        elif s.status == "interrupted":
             name += " (Interrupted)"

        spans.append({
            "span_id": sid,
            "parent_span_id": str(s.parent_span_id) if s.parent_span_id else None,
            "type": s.span_type,
            "name": name,
            "status": s.status,
            "duration": (s.ended_at - s.started_at).total_seconds() if s.ended_at else None
        })

    # Visual Polish: If run is interrupted, mark the last span as interrupted too
    if run.status == "interrupted" and spans:
        last_span = spans[-1]
        if last_span["status"] in ["succeeded", "running"]:
             last_span["status"] = "interrupted"
             if "(Interrupted)" not in last_span["name"] and "(Waiting for Approval)" not in last_span["name"]:
                 last_span["name"] += " (Interrupted)"

    # 5. Get Interrupts Count
    from app.models.db_models import ApprovalRequestModel
    interrupts_res = await db.execute(
        select(func.count())
        .where(ApprovalRequestModel.request_id == real_request_id)
    )
    interrupts_count = interrupts_res.scalar_one()

    # Summary Object
    duration = (run.ended_at - run.started_at).total_seconds() if run.ended_at else None
    summary = AuditRunSummary(
        request_id=str(run.request_id),
        time=run.started_at,
        root_agent_name=run.root_agent_name,
        status=run.status,
        duration_seconds=duration,
        initiator=run.initiator_id,
        conversation_id=run.conversation_id,
        session_id=run.conversation_id,
        llm_calls_count=llm_count,
        tool_calls_count=tool_count,
        failures_count=len(failures),
        interrupts_count=interrupts_count
    )
    
    return RunDetailView(
        run=summary,
        failures=failures,
        spans=spans,
        recent_events=event_views
    )
