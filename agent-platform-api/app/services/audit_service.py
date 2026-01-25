import logging
import json
from uuid import UUID
from datetime import datetime
from typing import Dict, Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.db_models import (
    AgentRunModel, AgentSpanModel, AuditEventModel, ToolAuditModel, AuditBlobModel,
    ApprovalRequestModel, ApprovalDecisionModel
)

_LOGGER = logging.getLogger(__name__)

class AuditPersistenceService:
    """Service to persist audit events to normalized DB tables."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        
    async def process_event(self, event: Dict[str, Any]):
        """Process a standardized audit event."""
        # 1. Parse standard fields
        event_type = event.get("event_type")
        run_id_str = event.get("run_id")
        span_id_str = event.get("span_id")
        # Ensure we have run_id. If missing, we can't do much relational stuff.
        if not run_id_str:
            _LOGGER.warning(f"Skipping event {event_type} without run_id")
            return
        
        try:
            run_id = UUID(run_id_str)
            span_id = UUID(span_id_str) if span_id_str else None
        except ValueError:
            _LOGGER.warning(f"Skipping event {event_type} with invalid run_id/span_id: {run_id_str}/{span_id_str}")
            return
        
        # 2. Extract payload
        payload_json = event.get("payload_json", "{}")
        try:
            payload = json.loads(payload_json)
        except:
            payload = {}
            
        # 3. Ensure Run Exists (Idempotent) to satisfy Foreign Keys
        # This handles out-of-order events where child arrives before parent
        await self._ensure_run_exists(run_id, event.get("session_id"), event.get("thread_id"))
        
        # Handle Span Start explicitly if needed for Span FKs (chains/tools)
        if event_type in ("chain_start", "run_started", "tool_call_requested", "llm_called", "langgraph_node_started"):
            await self._handle_span_start(run_id, span_id, event_type, payload, event)

        # Ensure Span Exists (Idempotent) to satisfy FK
        if span_id:
            await self._ensure_span_exists(run_id, span_id, event.get("session_id"), event.get("thread_id"))

        # 4. Create AuditEventModel (Timeline)
        # Wrap in nested transaction to ignore duplicates (idempotency)
        try:
            async with self.db.begin_nested():
                audit_event = AuditEventModel(
                    event_id=UUID(event["event_id"]) if event.get("event_id") else None,
                    run_id=run_id,
                    span_id=span_id,
                    session_id=event.get("session_id"),
                    thread_id=event.get("thread_id"),
                    event_type=event_type,
                    actor_type=event.get("actor_type"),
                    actor_id=event.get("actor_id"),
                    component=event.get("component"), 
                    payload=payload,
                    # event_time handled by default or parsed if string provided
                )
                self.db.add(audit_event)
                await self.db.flush()
        except (IntegrityError, Exception) as e:
            msg = str(e)
            if "duplicate key" in msg or "UniqueViolation" in msg or "already exists" in msg:
                _LOGGER.info(f"Event {event.get('event_id')} already exists. Skipping insertion but proceeding with state updates.")
                _LOGGER.info(f"Continuing to process event type: {event_type} for run {run_id} span {span_id}")
            else:
                raise e
        
        # 5. Handle State Transitions (End / Other)
        if event_type == "run_started":
            await self._handle_run_start(run_id, event.get("session_id"), event.get("thread_id"), payload)
            
        elif event_type in ("run_finished", "run_failed", "run_interrupted"):
            await self._handle_run_end(run_id, event_type, payload)
            
        elif event_type in ("chain_end", "tool_call_executed", "llm_output_received", "tool_val_failed", "llm_failed", "langgraph_node_finished", "node_failed", "chain_interrupted"):
            await self._handle_span_end(span_id, event_type, payload)
            
            # Extra specialized handling
            if "tool" in event_type:
                await self._handle_tool_audit(run_id, span_id, event_type, payload, event.get("session_id"), event.get("thread_id"))
 
        elif event_type == "hitl_requested":
            # HITL Request depends on Run/Span. They should exist.
            await self._handle_hitl_request(run_id, span_id, payload)
        elif event_type in ("hitl_approved", "hitl_rejected"):
            await self._handle_hitl_decision(run_id, span_id, event_type, payload)
            
            
        await self.db.commit()

    async def _ensure_run_exists(self, run_id: UUID, session_id: str | None, thread_id: str | None):
        """Ensure AgentRunModel exists. Idempotent."""
        existing = await self.db.get(AgentRunModel, run_id)
        if existing:
            return
            
        try:
             # Force INSERT via nested transaction to handle race conditions
            async with self.db.begin_nested():
                # For robustness, handle case where run might have been created by another worker
                # but not yet committed? No, consistent read.
                # Just insert.
                run = AgentRunModel(
                    run_id=run_id,
                    status="running",
                    conversation_id=session_id,
                    thread_id=thread_id
                )
                self.db.add(run)
                await self.db.flush()
        except Exception as e:
            # Log errors (usually IntegrityError) but continue
            _LOGGER.error(f"Ensure Run {run_id} failed: {e}")
            pass

    async def _ensure_span_exists(self, run_id: UUID, span_id: UUID, session_id: str | None, thread_id: str | None):
        """Ensure AgentSpanModel exists. Idempotent."""
        existing = await self.db.get(AgentSpanModel, span_id)
        if existing:
            return
            
        try:
            async with self.db.begin_nested():
                span = AgentSpanModel(
                    span_id=span_id,
                    run_id=run_id,
                    span_type="unknown",
                    agent_name="unknown", 
                    status="running",
                    # created_at and started_at default to now
                    started_at=datetime.utcnow()
                )
                self.db.add(span)
                await self.db.flush()
        except Exception as e:
            # Log errors but continue (e.g. FK violation if run missing)
            _LOGGER.error(f"Ensure Span {span_id} failed: {e}")
            pass

    async def _handle_run_start(self, run_id: UUID, session_id: str | None, thread_id: str | None, payload: Dict[str, Any]):
        """Create or Update AgentRunModel."""
        agent_name = payload.get("root_agent_name", "unknown")
        
        existing = await self.db.get(AgentRunModel, run_id)
        if existing:
            if (existing.root_agent_name is None or existing.root_agent_name == "unknown") and agent_name != "unknown":
                existing.root_agent_name = agent_name
            return
            
        run = AgentRunModel(
            run_id=run_id,
            status="running",
            conversation_id=session_id,
            thread_id=thread_id,
            root_agent_name=agent_name
        )
        self.db.add(run)

    async def _handle_run_end(self, run_id: UUID, event_type: str, payload: Dict[str, Any]):
        """Update AgentRunModel."""
        if event_type == "run_finished":
            status = "succeeded"
        elif event_type == "run_interrupted":
            status = "interrupted"
        else:
            status = "failed"
            
        stmt = update(AgentRunModel).where(AgentRunModel.run_id == run_id)
        
        # Prevent overwriting 'interrupted' or 'failed' with 'succeeded'
        # This handles cases where run_interrupted happens, followed by run_finished cleanup
        if status == "succeeded":
            stmt = stmt.where(AgentRunModel.status.not_in(["interrupted", "failed"]))

        stmt = stmt.values(
            status=status,
            ended_at=datetime.utcnow()
        )
        if status == "failed":
            stmt = stmt.values(
                error_message=payload.get("error_message"),
                error_code=payload.get("error_class")
            )
        await self.db.execute(stmt)

    async def _handle_span_start(self, run_id: UUID, span_id: UUID | None, event_type: str, payload: Dict[str, Any], event: Dict[str, Any]):
        """Create AgentSpanModel."""
        if not span_id:
            return
            
        existing = await self.db.get(AgentSpanModel, span_id)
        if existing:
            return

        span_type = "chain"
        if "tool" in event_type: span_type = "tool"
        elif "llm" in event_type: span_type = "llm"
        elif "node" in event_type: span_type = "node"
        
        # Extract meaningful names
        node_name = payload.get("name") or event.get("name")
        # For LangGraph nodes
        if not node_name and "langgraph_node" in payload:  
             node_name = payload["langgraph_node"]
        if not node_name and "langgraph_node" in event:
             node_name = event["langgraph_node"]
        
        # Extract metadata
        subagent_kind = payload.get("subagent")
        
        # Infer from parent "task" tool if generic LangGraph span
        if (node_name == "LangGraph" or not subagent_kind) and event.get("parent_span_id"):
             try:
                 parent = await self.db.get(AgentSpanModel, UUID(event["parent_span_id"]))
                 if parent and parent.meta and parent.meta.get("tool_name") == "task":
                     digest = parent.meta.get("input_digest")
                     if digest:
                         import ast
                         try:
                             # Handle potential truncation or formatting issues gracefully
                             inputs = ast.literal_eval(digest)
                             if isinstance(inputs, dict) and "subagent_type" in inputs:
                                 subagent_kind = inputs["subagent_type"]
                                 if node_name == "LangGraph":
                                     node_name = subagent_kind
                         except:
                             pass
             except Exception as e:
                 _LOGGER.warning(f"Failed to infer context from parent span: {e}")

        # Resolve Parent Span ID (LangChain often sends parent_run_id)
        raw_parent_id = event.get("parent_span_id") or event.get("parent_run_id")
        parent_uuid = UUID(raw_parent_id) if raw_parent_id else None

        span = AgentSpanModel(
            span_id=span_id,
            run_id=run_id,
            parent_span_id=parent_uuid,
            span_type=span_type,
            agent_name=event.get("component"), 
            node_name=node_name,
            subagent_kind=subagent_kind,
            status="running",
            meta=payload # Store initial inputs in meta
        )
        self.db.add(span)

    async def _handle_span_end(self, span_id: UUID | None, event_type: str, payload: Dict[str, Any]):
        """Update AgentSpanModel."""
        if not span_id:
            return
            
        if "failed" in event_type:
            status = "failed"
        elif "interrupted" in event_type:
            status = "interrupted"
        else:
            status = "succeeded"

        _LOGGER.info(f"Updating Span {span_id} status to {status} due to {event_type}")

        stmt = update(AgentSpanModel).where(AgentSpanModel.span_id == span_id)
        
        # Prevent overwriting 'interrupted' or 'failed' with 'succeeded'
        if status == "succeeded":
            stmt = stmt.where(AgentSpanModel.status.not_in(["interrupted", "failed"]))

        stmt = stmt.values(
            status=status,
            ended_at=datetime.utcnow()
        )
        await self.db.execute(stmt)

    async def _handle_tool_audit(self, run_id: UUID, span_id: UUID | None, event_type: str, payload: Dict[str, Any], session_id: str | None, thread_id: str | None):
        """Populate ToolAuditModel on completion."""
        from uuid import uuid4
        
        if not span_id:
            return
            
        # We try to get tool_name from existing span if not in payload (end event usually lacks name)
        tool_name = payload.get("tool_name", "unknown")
        if tool_name == "unknown":
            # Query db for span meta? or just leave unknown. 
            # For efficiency we might skip db query and fix it by ensuring emitter sends name in end event?
            # Or assume start event has already populated span meta.
            # But ToolAuditModel is a separate table.
            pass

        tool_audit = ToolAuditModel(
            tool_event_id=uuid4(),
            run_id=run_id,
            span_id=span_id,
            session_id=session_id,
            thread_id=thread_id,
            tool_name=tool_name, 
            tool_version="1.0",
            request_time=datetime.utcnow(), 
            response_time=datetime.utcnow(),
            status="failed" if "failed" in event_type else "succeeded",
            output_digest=payload.get("output_digest"),
            error=payload if "failed" in event_type else None,
            side_effect_level="read" # Default
        )
        self.db.add(tool_audit)

    async def _handle_hitl_request(self, run_id: UUID, span_id: UUID | None, payload: Dict[str, Any]):
        """Create ApprovalRequestModel."""
        from uuid import uuid4
        
        # Determine risk level or action type from payload
        action_type = payload.get("tool_name", "unknown")
        
        req = ApprovalRequestModel(
            approval_id=uuid4(),
            run_id=run_id,
            span_id=span_id,
            requested_at=datetime.utcnow(),
            action_type=action_type,
            risk_level="high", # Default for now
            status="pending",
            # proposed_action_blob_id we might skip or store simple payload
        )
        self.db.add(req)

    async def _handle_hitl_decision(self, run_id: UUID, span_id: UUID | None, event_type: str, payload: Dict[str, Any]):
        """Create ApprovalDecisionModel and update Request."""
        from uuid import uuid4
        
        # Find pending request
        stmt = select(ApprovalRequestModel).where(
            ApprovalRequestModel.run_id == run_id,
            ApprovalRequestModel.status == "pending"
        ).order_by(ApprovalRequestModel.requested_at.desc()).limit(1)
        
        res = await self.db.execute(stmt)
        req = res.scalar_one_or_none()
        
        if not req:
            _LOGGER.warning(f"Received HITL decision but no pending request found for run_id={run_id}")
            # Still record decision? Or skip? 
            # If we skip, we lose audit trail of the decision.
            # But we can't link FK.
            # We'll skip for now or create a detached decision if validation allowed (FK required).
            return

        decision_val = "approved" if event_type == "hitl_approved" else "rejected"
        
        # Update Request Status
        req.status = decision_val
        # self.db.add(req) # Already attached
        
        # Create Decision Record
        decision = ApprovalDecisionModel(
            decision_id=uuid4(),
            approval_id=req.approval_id,
            decided_at=datetime.utcnow(),
            decider_id=payload.get("actor_id", "user"), # or from payload
            decision=decision_val,
            reason=payload.get("reason", "")
        )
        self.db.add(decision)
