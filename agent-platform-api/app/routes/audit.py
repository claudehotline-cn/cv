from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Any, Dict, Tuple
from datetime import datetime, timedelta, timezone
from uuid import UUID
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, String, func, or_, and_

from app.db import get_db
from app.models.db_models import AgentRunModel, AuditEventModel, AgentSpanModel, AuthAuditEventModel
from app.core.auth import AuthPrincipal, require_admin

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
    action_type: str = "chain"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    token_source: str = "none"

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
    insights: Dict[str, Any] = {}


class AuditOverviewView(BaseModel):
    window_hours: int
    total_requests: int
    avg_latency_ms: float
    total_tokens: int
    succeeded_requests: int
    failed_requests: int
    interrupted_requests: int
    running_requests: int


class AuthAuditEventView(BaseModel):
    event_id: str
    event_time: datetime
    event_type: str
    user_id: Optional[str]
    email: Optional[str]
    actor_type: Optional[str]
    actor_id: Optional[str]
    ip_addr: Optional[str]
    user_agent: Optional[str]
    result: Optional[str]
    reason_code: Optional[str]
    payload: Dict[str, Any]


class PaginatedAuthAuditResponse(BaseModel):
    items: List[AuthAuditEventView]
    total: int
    limit: int
    offset: int


class AuthAuditOverviewResponse(BaseModel):
    window_hours: int
    total_events: int
    login_success: int
    login_failed: int
    login_success_rate: float
    unique_user_count: int
    unique_ip_count: int
    top_failure_reasons: Dict[str, int]


LLM_EVENT_TYPES = {"llm_called", "llm_output_received", "llm_failed"}
TOOL_EVENT_TYPES = {"tool_call_requested", "tool_call_executed", "tool_failed", "tool_val_failed"}


def _as_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(float(value))
    except Exception:
        return 0


def _clip_text(value: Any, max_len: int = 4000) -> str:
    if value is None:
        return ""
    text = str(value)
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _estimate_tokens_from_text(value: Any) -> int:
    text = _clip_text(value, max_len=12000)
    if not text:
        return 0
    return max(1, len(text) // 4)


def _extract_usage_dict(payload: Dict[str, Any]) -> Tuple[int, int, int, str]:
    usage = payload.get("token_usage")
    if not isinstance(usage, dict):
        return 0, 0, 0, "none"

    prompt = _as_int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("prompt_token_count")
        or usage.get("input_token_count")
    )
    completion = _as_int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("completion_token_count")
        or usage.get("output_token_count")
    )
    total = _as_int(
        usage.get("total_tokens")
        or usage.get("total")
        or usage.get("token_count")
    )

    if total <= 0:
        total = prompt + completion

    if total <= 0:
        return 0, 0, 0, "none"

    if prompt <= 0 and completion <= 0:
        prompt = int(total * 0.6)
        completion = total - prompt

    if completion <= 0:
        completion = max(total - prompt, 0)
    if prompt <= 0:
        prompt = max(total - completion, 0)

    return prompt, completion, total, "exact"


def _is_failure_event(event_type: str, severity: Optional[str]) -> bool:
    sev = (severity or "").lower()
    et = (event_type or "").lower()
    return sev == "error" or "failed" in et or et in {"run_failed", "job_failed", "job_timed_out"}


def _is_interrupt_event(event_type: str, severity: Optional[str]) -> bool:
    et = (event_type or "").lower()
    sev = (severity or "").lower()
    return "interrupt" in et or et in {"hitl_requested", "job_waiting_approval"} or sev == "interrupt"


def _derive_action_type(llm_calls: int, tool_calls: int, interrupts: int, span_types: Optional[set[str]] = None) -> str:
    if llm_calls > 0 and tool_calls > 0:
        return "chain"
    if llm_calls > 0:
        return "llm"
    if tool_calls > 0:
        return "tool"
    if interrupts > 0:
        return "interrupt"
    if span_types and "job" in span_types:
        return "job"
    return "chain"


def _normalize_action_filter(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().lower()
    aliases = {
        "llm_call": "llm",
        "llm": "llm",
        "tool_use": "tool",
        "tool": "tool",
        "chain": "chain",
        "interrupt": "interrupt",
        "job": "job",
    }
    return aliases.get(v)


def _extract_preview_payload(events: List[AuditEventModel], key_candidates: List[str]) -> Optional[str]:
    for e in events:
        payload = e.payload if isinstance(e.payload, dict) else {}
        for k in key_candidates:
            if payload.get(k):
                return _clip_text(payload.get(k), 6000)
    return None


def _first_non_empty(values: List[Optional[str]]) -> Optional[str]:
    for value in values:
        if value:
            return value
    return None


def _resolve_session_id(run: AgentRunModel, events: List[AuditEventModel]) -> Optional[str]:
    event_session_id = next((e.session_id for e in events if e.session_id), None)
    return _first_non_empty([event_session_id, run.conversation_id])


def _resolve_thread_id(run: AgentRunModel, events: List[AuditEventModel]) -> Optional[str]:
    event_thread_id = next((e.thread_id for e in events if e.thread_id), None)
    return _first_non_empty([run.thread_id, event_thread_id])


def _parse_float(v: Any) -> float:
    try:
        if v is None:
            return 0.0
        return float(v)
    except Exception:
        return 0.0


@router.get("/auth/events", response_model=PaginatedAuthAuditResponse)
async def list_auth_audit_events(
    limit: int = 50,
    offset: int = 0,
    event_type: Optional[str] = None,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    ip_addr: Optional[str] = None,
    result: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuthAuditEventModel)

    if event_type:
        stmt = stmt.where(AuthAuditEventModel.event_type == event_type)
    if user_id:
        stmt = stmt.where(AuthAuditEventModel.user_id == user_id)
    if email:
        stmt = stmt.where(AuthAuditEventModel.email.ilike(f"%{email}%"))
    if ip_addr:
        stmt = stmt.where(AuthAuditEventModel.ip_addr == ip_addr)
    if result:
        stmt = stmt.where(AuthAuditEventModel.result == result)
    if start_date:
        stmt = stmt.where(AuthAuditEventModel.event_time >= start_date)
    if end_date:
        stmt = stmt.where(AuthAuditEventModel.event_time <= end_date)

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total_res = await db.execute(total_stmt)
    total = int(total_res.scalar_one() or 0)

    rows_stmt = stmt.order_by(desc(AuthAuditEventModel.event_time)).limit(limit).offset(offset)
    rows_res = await db.execute(rows_stmt)
    rows = rows_res.scalars().all()

    items = [
        AuthAuditEventView(
            event_id=str(r.event_id),
            event_time=r.event_time,
            event_type=r.event_type,
            user_id=r.user_id,
            email=r.email,
            actor_type=r.actor_type,
            actor_id=r.actor_id,
            ip_addr=r.ip_addr,
            user_agent=r.user_agent,
            result=r.result,
            reason_code=r.reason_code,
            payload=r.payload or {},
        )
        for r in rows
    ]

    return PaginatedAuthAuditResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/auth/overview", response_model=AuthAuditOverviewResponse)
async def get_auth_audit_overview(
    window_hours: int = 24,
    user_id: Optional[str] = None,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=max(1, min(window_hours, 24 * 30)))

    base_filter = AuthAuditEventModel.event_time >= window_start
    if user_id:
        base_filter = and_(base_filter, AuthAuditEventModel.user_id == user_id)

    total_q = await db.execute(
        select(func.count()).where(base_filter).select_from(AuthAuditEventModel)
    )
    total_events = int(total_q.scalar_one() or 0)

    success_q = await db.execute(
        select(func.count())
        .where(and_(base_filter, AuthAuditEventModel.event_type == "auth_login_succeeded"))
        .select_from(AuthAuditEventModel)
    )
    login_success = int(success_q.scalar_one() or 0)

    failed_q = await db.execute(
        select(func.count())
        .where(and_(base_filter, AuthAuditEventModel.event_type == "auth_login_failed"))
        .select_from(AuthAuditEventModel)
    )
    login_failed = int(failed_q.scalar_one() or 0)

    unique_user_q = await db.execute(
        select(func.count(func.distinct(AuthAuditEventModel.user_id))).where(base_filter)
    )
    unique_user_count = int(unique_user_q.scalar_one() or 0)

    unique_ip_q = await db.execute(
        select(func.count(func.distinct(AuthAuditEventModel.ip_addr))).where(base_filter)
    )
    unique_ip_count = int(unique_ip_q.scalar_one() or 0)

    reason_q = await db.execute(
        select(AuthAuditEventModel.reason_code, func.count())
        .where(and_(base_filter, AuthAuditEventModel.result == "failed"))
        .group_by(AuthAuditEventModel.reason_code)
        .order_by(desc(func.count()))
        .limit(10)
    )
    top_failure_reasons = {
        (reason or "unknown"): int(cnt)
        for reason, cnt in reason_q.all()
    }

    login_total = login_success + login_failed
    success_rate = (login_success / login_total) if login_total > 0 else 0.0

    return AuthAuditOverviewResponse(
        window_hours=window_hours,
        total_events=total_events,
        login_success=login_success,
        login_failed=login_failed,
        login_success_rate=round(success_rate, 4),
        unique_user_count=unique_user_count,
        unique_ip_count=unique_ip_count,
        top_failure_reasons=top_failure_reasons,
    )


def _collect_event_stats(events: List[AuditEventModel]) -> Dict[str, int]:
    out = {"llm": 0, "tool": 0, "fail": 0, "interrupt": 0}
    for e in events:
        et = e.event_type or ""
        sev = e.severity
        if et == "llm_called":
            out["llm"] += 1
        if et == "tool_call_executed":
            out["tool"] += 1
        if _is_failure_event(et, sev):
            out["fail"] += 1
        if _is_interrupt_event(et, sev):
            out["interrupt"] += 1
    return out


def _aggregate_token_counts(events: List[AuditEventModel]) -> Tuple[int, int, int, str]:
    prompt_total = 0
    completion_total = 0
    total_total = 0
    token_source = "none"
    prompt_digest_by_span: Dict[str, str] = {}

    for e in events:
        payload = e.payload if isinstance(e.payload, dict) else {}
        sid = str(e.span_id) if e.span_id else None
        et = e.event_type or ""

        if et == "llm_called" and sid:
            prompt_digest = (
                payload.get("messages_digest")
                or payload.get("prompts_digest")
                or payload.get("inputs_digest")
            )
            if prompt_digest:
                prompt_digest_by_span[sid] = str(prompt_digest)

        if et != "llm_output_received":
            continue

        prompt, completion, total, source = _extract_usage_dict(payload)

        if source == "none":
            prompt_text = (
                prompt_digest_by_span.get(sid or "")
                or payload.get("messages_digest")
                or payload.get("prompts_digest")
            )
            completion_text = payload.get("generations_digest") or payload.get("outputs_digest")
            prompt = _estimate_tokens_from_text(prompt_text)
            completion = _estimate_tokens_from_text(completion_text)
            total = prompt + completion
            source = "estimated" if total > 0 else "none"

        if total <= 0:
            continue

        prompt_total += prompt
        completion_total += completion
        total_total += total

        if source == "exact":
            token_source = "exact"
        elif source == "estimated" and token_source == "none":
            token_source = "estimated"

    return prompt_total, completion_total, total_total, token_source

@router.get("/overview", response_model=AuditOverviewView)
async def get_audit_overview(
    window_hours: int = 24,
    agent: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Overview KPI for audit dashboard."""
    window_hours = max(1, min(window_hours, 168))
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    stmt = select(AgentRunModel).where(AgentRunModel.started_at >= since)
    if agent:
        stmt = stmt.where(AgentRunModel.root_agent_name == agent)

    runs_res = await db.execute(stmt)
    runs = runs_res.scalars().all()
    run_ids = [r.request_id for r in runs]

    durations_ms: List[float] = []
    succeeded = 0
    failed = 0
    interrupted = 0
    running = 0

    for r in runs:
        s = (r.status or "").lower()
        if s == "succeeded":
            succeeded += 1
        elif s == "failed":
            failed += 1
        elif s in {"interrupted", "cancelled"}:
            interrupted += 1
        elif s == "running":
            running += 1

        if r.ended_at and r.started_at:
            durations_ms.append(max((r.ended_at - r.started_at).total_seconds() * 1000.0, 0.0))

    total_tokens = 0
    if run_ids:
        token_evt_stmt = (
            select(AuditEventModel)
            .where(AuditEventModel.request_id.in_(run_ids))
            .where(AuditEventModel.event_type.in_(["llm_called", "llm_output_received"]))
            .order_by(AuditEventModel.event_time)
        )
        token_evt_res = await db.execute(token_evt_stmt)
        token_events = token_evt_res.scalars().all()

        by_run: Dict[UUID, List[AuditEventModel]] = defaultdict(list)
        for e in token_events:
            by_run[e.request_id].append(e)

        for rid in run_ids:
            _, _, total, _ = _aggregate_token_counts(by_run.get(rid, []))
            total_tokens += total

    avg_latency_ms = round(sum(durations_ms) / len(durations_ms), 2) if durations_ms else 0.0

    return AuditOverviewView(
        window_hours=window_hours,
        total_requests=len(runs),
        avg_latency_ms=avg_latency_ms,
        total_tokens=total_tokens,
        succeeded_requests=succeeded,
        failed_requests=failed,
        interrupted_requests=interrupted,
        running_requests=running,
    )


@router.get("/runs", response_model=PaginatedRunsResponse)
async def list_runs(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    q: Optional[str] = None,
    action: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
):
    """List agent runs with summary statistics and semantic fields for UI."""
    normalized_action = _normalize_action_filter(action)

    stmt = select(AgentRunModel)

    if status:
        stmt = stmt.where(AgentRunModel.status == status)
    if agent:
        stmt = stmt.where(AgentRunModel.root_agent_name == agent)

    if q:
        stmt = stmt.where(
            or_(
                AgentRunModel.request_id.cast(String).ilike(f"%{q}%"),
                AgentRunModel.conversation_id.ilike(f"%{q}%"),
                AgentRunModel.initiator_id.ilike(f"%{q}%"),
            )
        )

    if start_date:
        stmt = stmt.where(AgentRunModel.started_at >= start_date)
    if end_date:
        stmt = stmt.where(AgentRunModel.started_at <= end_date)

    if normalized_action:
        action_map = {
            "llm": list(LLM_EVENT_TYPES),
            "tool": list(TOOL_EVENT_TYPES),
            "interrupt": ["hitl_requested", "job_waiting_approval", "run_interrupted", "chain_interrupted"],
            "job": ["job_queued", "job_started", "job_completed", "job_failed", "job_cancelled", "job_timed_out"],
            "chain": ["chain_start", "chain_end", "subagent_started", "subagent_finished"],
        }
        action_events = action_map.get(normalized_action)
        if action_events:
            action_subquery = (
                select(AuditEventModel.request_id)
                .where(AuditEventModel.event_type.in_(action_events))
                .group_by(AuditEventModel.request_id)
            )
            stmt = stmt.where(AgentRunModel.request_id.in_(action_subquery))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_res = await db.execute(count_stmt)
    total = total_res.scalar_one()

    rows_stmt = stmt.order_by(desc(AgentRunModel.started_at)).limit(limit).offset(offset)
    rows_res = await db.execute(rows_stmt)
    runs = rows_res.scalars().all()
    run_ids = [r.request_id for r in runs]

    events_by_run: Dict[UUID, List[AuditEventModel]] = defaultdict(list)
    span_types_by_run: Dict[UUID, set[str]] = defaultdict(set)
    interrupt_counts: Dict[UUID, int] = defaultdict(int)

    if run_ids:
        event_stmt = (
            select(AuditEventModel)
            .where(AuditEventModel.request_id.in_(run_ids))
            .where(
                or_(
                    AuditEventModel.event_type.in_(
                        [
                            "llm_called",
                            "llm_output_received",
                            "llm_failed",
                            "tool_call_executed",
                            "tool_failed",
                            "tool_val_failed",
                            "hitl_requested",
                            "job_waiting_approval",
                            "run_interrupted",
                            "chain_interrupted",
                            "job_failed",
                            "run_failed",
                        ]
                    ),
                    AuditEventModel.severity.in_(["Error", "Interrupt"]),
                )
            )
            .order_by(AuditEventModel.event_time)
        )
        event_res = await db.execute(event_stmt)
        for e in event_res.scalars().all():
            events_by_run[e.request_id].append(e)

        from app.models.db_models import ApprovalRequestModel

        approval_stmt = (
            select(ApprovalRequestModel.request_id, func.count())
            .where(ApprovalRequestModel.request_id.in_(run_ids))
            .group_by(ApprovalRequestModel.request_id)
        )
        approval_res = await db.execute(approval_stmt)
        for rid, cnt in approval_res:
            interrupt_counts[rid] = int(cnt)

        span_stmt = select(AgentSpanModel.request_id, AgentSpanModel.span_type).where(AgentSpanModel.request_id.in_(run_ids))
        span_res = await db.execute(span_stmt)
        for rid, span_type in span_res:
            if span_type:
                span_types_by_run[rid].add(span_type)

    items: List[AuditRunSummary] = []
    for r in runs:
        duration = None
        if r.ended_at and r.started_at:
            duration = max((r.ended_at - r.started_at).total_seconds(), 0.0)

        run_events = events_by_run.get(r.request_id, [])
        resolved_session_id = _resolve_session_id(r, run_events)
        event_stats = _collect_event_stats(run_events)
        prompt_tokens, completion_tokens, total_tokens, token_source = _aggregate_token_counts(run_events)
        interrupt_count = interrupt_counts.get(r.request_id, event_stats.get("interrupt", 0))

        action_type = _derive_action_type(
            llm_calls=event_stats.get("llm", 0),
            tool_calls=event_stats.get("tool", 0),
            interrupts=interrupt_count,
            span_types=span_types_by_run.get(r.request_id, set()),
        )

        items.append(
            AuditRunSummary(
                request_id=str(r.request_id),
                time=r.started_at,
                root_agent_name=r.root_agent_name or "Unknown Agent",
                status=r.status,
                duration_seconds=duration,
                initiator=r.initiator_id or "System",
                conversation_id=r.conversation_id,
                session_id=resolved_session_id,
                llm_calls_count=event_stats.get("llm", 0),
                tool_calls_count=event_stats.get("tool", 0),
                failures_count=event_stats.get("fail", 0),
                interrupts_count=interrupt_count,
                action_type=action_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                token_source=token_source,
            )
        )

    return PaginatedRunsResponse(items=items, total=total, limit=limit, offset=offset)

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
        .order_by(desc(AuditEventModel.event_time))
        .limit(200)
    )
    events = list(reversed(events_res.scalars().all()))
    
    # 3. Process Events into View Models
    failures: List[AuditEventView] = []
    event_views: List[AuditEventView] = []
    span_names: Dict[str, str] = {}
    llm_span_latencies_ms: List[float] = []
    llm_call_time_by_span: Dict[str, datetime] = {}

    for e in events:
        event_type = e.event_type or ""
        payload = e.payload if isinstance(e.payload, dict) else {}

        severity = "Info"
        if "interrupted" in event_type:
            severity = "Interrupt"
        elif "error" in event_type or "failed" in event_type:
            if payload.get("error_class") in ["GraphInterrupt", "NodeInterrupt"]:
                severity = "Interrupt"
            else:
                severity = "Error"
        elif event_type == "job_timed_out":
            severity = "Error"
        elif "end" in event_type or event_type == "job_completed":
            severity = "Success"
        elif event_type == "job_cancelled":
            severity = "Interrupt"

        if e.span_id:
            sid = str(e.span_id)
            if "model" in payload:
                span_names[sid] = f"LLM: {payload['model']}"
            elif "tool_name" in payload:
                span_names[sid] = f"Tool: {payload['tool_name']}"

            if event_type == "llm_called":
                llm_call_time_by_span[sid] = e.event_time
            if event_type == "llm_output_received":
                started_at = llm_call_time_by_span.get(sid)
                if started_at:
                    delta_ms = max((e.event_time - started_at).total_seconds() * 1000.0, 0.0)
                    llm_span_latencies_ms.append(delta_ms)

        msg = event_type
        if payload:
            if event_type.startswith("job_"):
                if event_type == "job_progress":
                    progress = payload.get("progress")
                    stage_msg = payload.get("message") or payload.get("stage")
                    if progress is not None and stage_msg:
                        msg = f"{progress}% - {stage_msg}"
                    elif progress is not None:
                        msg = f"{progress}%"
                    elif stage_msg:
                        msg = str(stage_msg)
                elif event_type == "job_queued":
                    title = payload.get("title")
                    queue = payload.get("queue")
                    msg = f"Queued: {title}" if title else "Job queued"
                    if queue:
                        msg += f" (queue={queue})"
                elif event_type == "job_started":
                    title = payload.get("title")
                    msg = f"Started: {title}" if title else "Job started"
                elif event_type == "job_completed":
                    result = payload.get("result")
                    audit_url = result.get("audit_url") if isinstance(result, dict) else None
                    msg = f"Completed: {audit_url}" if audit_url else "Job completed"

            if msg == event_type and "error_message" in payload:
                msg = str(payload["error_message"])
            elif "tool_name" in payload:
                msg = f"Tool: {payload['tool_name']}"
            elif "model" in payload:
                msg = f"Model: {payload['model']}"
            elif "langgraph_node" in payload:
                node = payload["langgraph_node"]
                if "start" in event_type:
                    msg = f"Node '{node}' started"
                elif "end" in event_type or "finished" in event_type:
                    msg = f"Node '{node}' finished"
                else:
                    msg = f"Node: {node}"
            elif "name" in payload:
                name = payload["name"]
                if "start" in event_type:
                    msg = f"Start: {name}"
                elif "end" in event_type or "finished" in event_type:
                    msg = f"End: {name}"
                else:
                    msg = f"{name}"

        view = AuditEventView(
            event_id=str(e.event_id),
            time=e.event_time,
            type=event_type,
            component=e.component,
            message=msg,
            severity=severity,
            payload=payload,
            span_id=str(e.span_id) if e.span_id else None,
        )
        event_views.append(view)
        if severity == "Error":
            failures.append(view)

    event_stats = _collect_event_stats(events)
    prompt_tokens, completion_tokens, total_tokens, token_source = _aggregate_token_counts(events)

    from app.models.db_models import ApprovalRequestModel

    # 3b. Get Pending Approvals for Status Enrichment
    pending_stmt = select(ApprovalRequestModel).where(
        ApprovalRequestModel.request_id == real_request_id,
        ApprovalRequestModel.status == "pending",
    )
    pending_res = await db.execute(pending_stmt)
    pending_reqs = pending_res.scalars().all()
    pending_map = {str(r.span_id): r for r in pending_reqs if r.span_id}

    # 4. Get Spans
    spans_res = await db.execute(
        select(AgentSpanModel)
        .where(AgentSpanModel.request_id == real_request_id)
        .order_by(AgentSpanModel.started_at)
    )
    db_spans = spans_res.scalars().all()

    job_root_id = None
    span_types: set[str] = set()
    span_type_duration_ms: Dict[str, float] = defaultdict(float)
    resource_rows: List[Dict[str, Any]] = []

    for s in db_spans:
        if s.span_type == "job" and not s.parent_span_id:
            job_root_id = s.span_id
            break

    spans: List[Dict[str, Any]] = []
    for s in db_spans:
        sid = str(s.span_id)
        span_types.add(s.span_type or "unknown")

        name = s.node_name or s.agent_name or "Unknown"
        if sid in span_names:
            name = span_names[sid]
        elif run.root_agent_name and s.span_type == "chain":
            if (not s.parent_span_id) or (job_root_id and s.parent_span_id == job_root_id):
                name = run.root_agent_name
        elif isinstance(name, str) and name.lower() in ["agent", "chain", "tool", "llm"]:
            name = name.upper() if name.lower() == "llm" else name.capitalize()

        if name == "Tools" and s.subagent_kind:
            clean_sub = s.subagent_kind.replace("_", " ").title()
            name = f"{clean_sub} Tools"

        if sid in pending_map:
            name += " (Waiting for Approval)"
        elif s.status == "interrupted":
            name += " (Interrupted)"

        span_duration = (s.ended_at - s.started_at).total_seconds() if s.ended_at and s.started_at else None
        if span_duration is not None:
            span_type_duration_ms[s.span_type or "unknown"] += max(span_duration * 1000.0, 0.0)

        spans.append(
            {
                "span_id": sid,
                "parent_span_id": str(s.parent_span_id) if s.parent_span_id else None,
                "type": s.span_type,
                "name": name,
                "status": s.status,
                "duration": span_duration,
                "started_at": s.started_at,
                "ended_at": s.ended_at,
                "agent_name": s.agent_name,
                "subagent_kind": s.subagent_kind,
                "node_name": s.node_name,
                "meta": s.meta or {},
            }
        )

        resource_rows.append(
            {
                "resource": name,
                "type": s.span_type,
                "status": s.status,
                "duration_ms": round(max((span_duration or 0.0) * 1000.0, 0.0), 2),
            }
        )

    # Visual polish: keep last span interrupted when run interrupted.
    if run.status == "interrupted" and spans:
        last_span = spans[-1]
        is_waiting_phase = (
            last_span.get("type") == "job_phase"
            and isinstance(last_span.get("name"), str)
            and last_span["name"].startswith("Waiting Approval")
            and last_span.get("status") == "running"
        )
        if not is_waiting_phase and last_span.get("status") in ["succeeded", "running"]:
            last_span["status"] = "interrupted"
            if "(Interrupted)" not in last_span["name"] and "(Waiting for Approval)" not in last_span["name"]:
                last_span["name"] += " (Interrupted)"

    # 5. Get Interrupts Count
    interrupts_res = await db.execute(
        select(func.count()).where(ApprovalRequestModel.request_id == real_request_id)
    )
    interrupts_count = max(int(interrupts_res.scalar_one() or 0), event_stats.get("interrupt", 0))

    duration = (run.ended_at - run.started_at).total_seconds() if run.ended_at and run.started_at else None
    total_latency_ms = round(max((duration or 0.0) * 1000.0, 0.0), 2)

    action_type = _derive_action_type(
        llm_calls=event_stats.get("llm", 0),
        tool_calls=event_stats.get("tool", 0),
        interrupts=interrupts_count,
        span_types=span_types,
    )

    model_name = None
    for e in events:
        payload = e.payload if isinstance(e.payload, dict) else {}
        if e.event_type == "llm_called" and payload.get("model"):
            model_name = str(payload.get("model"))
            break

    input_preview = _extract_preview_payload(
        events,
        ["messages_digest", "prompts_digest", "inputs_digest", "input_digest", "input"],
    )
    output_preview = _extract_preview_payload(
        list(reversed(events)),
        ["generations_digest", "outputs_digest", "output_digest", "result"],
    )

    inference_ms = round(span_type_duration_ms.get("llm", 0.0), 2)
    network_ms = round(span_type_duration_ms.get("tool", 0.0) + span_type_duration_ms.get("node", 0.0), 2)
    thinking_ms = round(max(total_latency_ms - inference_ms - network_ms, 0.0), 2)

    throughput_tps = None
    if inference_ms > 0 and completion_tokens > 0:
        throughput_tps = round(completion_tokens / (inference_ms / 1000.0), 2)

    ttft_ms = round(min(llm_span_latencies_ms), 2) if llm_span_latencies_ms else None
    context_window_utilization = round((total_tokens / 128000.0) * 100.0, 2) if total_tokens > 0 else 0.0

    estimated_cost_usd = None
    if model_name and total_tokens > 0:
        model_key = model_name.lower()
        pricing_per_1k = {
            "gpt-4o-mini": (0.00015, 0.00060),
            "gpt-4o": (0.00500, 0.01500),
        }
        for key, (prompt_rate, completion_rate) in pricing_per_1k.items():
            if key in model_key:
                estimated_cost_usd = round((prompt_tokens / 1000.0) * prompt_rate + (completion_tokens / 1000.0) * completion_rate, 6)
                break

    metadata_tags: List[str] = []
    if run.root_agent_name:
        metadata_tags.append(f"agent:{run.root_agent_name}")
    if run.status:
        metadata_tags.append(f"status:{run.status}")
    if run.env:
        metadata_tags.append(f"env:{run.env}")
    for tag in run.tags or []:
        if isinstance(tag, str):
            metadata_tags.append(tag)
    metadata_tags = list(dict.fromkeys(metadata_tags))
    resolved_session_id = _resolve_session_id(run, events)
    resolved_thread_id = _resolve_thread_id(run, events)

    summary = AuditRunSummary(
        request_id=str(run.request_id),
        time=run.started_at,
        root_agent_name=run.root_agent_name,
        status=run.status,
        duration_seconds=duration,
        initiator=run.initiator_id,
        conversation_id=run.conversation_id,
        session_id=resolved_session_id,
        llm_calls_count=event_stats.get("llm", 0),
        tool_calls_count=event_stats.get("tool", 0),
        failures_count=len(failures),
        interrupts_count=interrupts_count,
        action_type=action_type,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        token_source=token_source,
    )

    insights = {
        "primary_action": action_type,
        "model_name": model_name,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "token_source": token_source,
        "estimated_cost_usd": estimated_cost_usd,
        "input_preview": input_preview,
        "output_preview": output_preview,
        "latency_breakdown_ms": {
            "network": network_ms,
            "inference": inference_ms,
            "thinking": thinking_ms,
            "total": total_latency_ms,
        },
        "stats": {
            "ttft_ms": ttft_ms,
            "throughput_tps": throughput_tps,
            "context_window_utilization_pct": context_window_utilization,
        },
        "resource_details": resource_rows[:80],
        "metadata": {
            "environment": run.env,
            "initiator": run.initiator_id,
            "conversation_id": run.conversation_id,
            "thread_id": resolved_thread_id,
            "tags": metadata_tags,
        },
    }

    return RunDetailView(
        run=summary,
        failures=failures,
        spans=spans,
        recent_events=event_views,
        insights=insights,
    )
