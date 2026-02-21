import logging
import json
from uuid import UUID, uuid4, uuid5
from datetime import datetime, timezone
from typing import Dict, Any, List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, or_
from agent_core.settings import get_settings
from app.models.db_models import (
    AgentRunModel,
    AgentSpanModel,
    AuditEventModel,
    ToolAuditModel,
    AuditBlobModel,
    ApprovalRequestModel,
    ApprovalDecisionModel,
    AuthAuditEventModel,
)

_LOGGER = logging.getLogger(__name__)

class AuditPersistenceService:
    """Service to persist audit events to normalized DB tables."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        
    async def process_batch(self, events: List[Dict[str, Any]]):
        """Process a batch of events in a single transaction."""
        if not events:
            return

        try:
            # Single Transaction for the Batch
            # With DEFERRABLE Constraints, FKs are checked at Commit time.
            async with self.db.begin():
                for event in events:
                    await self._process_event_inner(event)
        except Exception as e:
            _LOGGER.error(f"Failed to process batch: {e}")
            # The transaction is rolled back automatically by context manager
            # We could implement a retry mechanism here or dead-letter queue
            raise e

    async def process_event(self, event: Dict[str, Any]):
        """Legacy wrapper for single event."""
        await self.process_batch([event])

    async def _process_event_inner(self, event: Dict[str, Any]):
        """Internal logic without transaction boundaries."""
        # Auth events are persisted into a dedicated table and do not depend on request/span IDs.
        if self._is_auth_event(event):
            await self._persist_auth_event(event)
            return

        # 1. Parse standard fields
        event_type = event.get("event_type")
        request_id_str = event.get("request_id")
        span_id_str = event.get("span_id")
        event_time = self._parse_event_time(event)
        
        if not request_id_str:
            _LOGGER.warning(f"Skipping event {event_type} without request_id")
            return
        
        try:
            request_id = UUID(request_id_str)
            span_id = UUID(span_id_str) if span_id_str else None
        except ValueError:
            _LOGGER.warning(f"Skipping event {event_type} with invalid request_id/span_id: {request_id_str}/{span_id_str}")
            return
        
        # 2. Extract payload
        payload_json = event.get("payload_json", "{}")
        try:
            payload = json.loads(payload_json)
        except:
            payload = {}

        tenant_id = self._resolve_tenant_id(event, payload)
            
        # 3. Ensure Run Exists (Idempotent)
        await self._ensure_run_exists(request_id, event.get("session_id"), event.get("thread_id"), tenant_id)

        is_job_event = isinstance(event_type, str) and event_type.startswith("job_")

        # Handle Span Start
        if is_job_event or event_type in ("chain_start", "subagent_started", "run_started", "tool_call_requested", "llm_called", "langgraph_node_started"):
            await self._handle_span_start(request_id, span_id, event_type or "unknown", payload, event)

        # Ensure Span Exists
        if span_id:
            await self._ensure_span_exists(request_id, span_id, event.get("session_id"), event.get("thread_id"))

        # Derive lightweight job lifecycle phases as child spans so they show in the tree.
        if is_job_event:
            await self._handle_job_phase_spans(
                request_id=request_id,
                event_type=event_type,
                event_time=event_time,
                session_id=event.get("session_id"),
                thread_id=event.get("thread_id"),
                payload=payload,
            )

        # 4. Create AuditEventModel
        # Use nested transaction ONLY for savepoint/rollback of THIS insert if conditional
        # But for batching, naive insert is fine. If unique violation, we skip.
        try:
             async with self.db.begin_nested():
                audit_event_kwargs: Dict[str, Any] = {
                    "event_id": UUID(event["event_id"]) if event.get("event_id") else None,
                    "tenant_id": tenant_id,
                    "request_id": request_id,
                    "span_id": span_id,
                    "session_id": event.get("session_id"),
                    "thread_id": event.get("thread_id"),
                    "event_type": event_type,
                    "actor_type": event.get("actor_type"),
                    "actor_id": event.get("actor_id"),
                    "component": event.get("component"),
                    "payload": payload,
                }
                if event_time is not None:
                    audit_event_kwargs["event_time"] = event_time

                audit_event = AuditEventModel(**audit_event_kwargs)
                self.db.add(audit_event)
                await self.db.flush()
        except IntegrityError:
             # Duplicate event - ignore
             _LOGGER.info(f"Event {event.get('event_id')} already exists. Skipping insertion but proceeding with state updates.")
             _LOGGER.info(f"Continuing to process event type: {event_type} for run {request_id} span {span_id}")
        except Exception as e:
             _LOGGER.error(f"Error inserting AuditEventModel for event {event.get('event_id')}: {e}")
        
        # 5. Handle State Transitions
        if event_type == "run_started":
            await self._handle_run_start(request_id, event.get("session_id"), event.get("thread_id"), payload, tenant_id)
            
        elif event_type in ("run_finished", "run_failed", "run_interrupted"):
            await self._handle_run_end(request_id, event_type, payload)

        elif event_type == "job_waiting_approval":
            await self._handle_job_pause(request_id, span_id, event_time)

        elif event_type == "job_resumed":
            await self._handle_job_resume(request_id, span_id)

        elif event_type in ("job_completed", "job_failed", "job_cancelled", "job_timed_out"):
            await self._handle_job_end(request_id, event_type, payload)
            await self._handle_span_end(request_id, span_id, event_type, payload)
            
        elif event_type in ("chain_end", "subagent_finished", "chain_failed", "tool_call_executed", "llm_output_received", "tool_val_failed", "llm_failed", "langgraph_node_finished", "node_failed", "chain_interrupted"):
            await self._handle_span_end(request_id, span_id, event_type, payload)
            
            # Extra specialized handling
            if "tool" in event_type:
                await self._handle_tool_audit(request_id, span_id, event_type, payload, event.get("session_id"), event.get("thread_id"))
 
        elif event_type == "hitl_requested":
            # HITL Request depends on Run/Span. They should exist.
            await self._handle_hitl_request(request_id, span_id, payload)
        elif event_type in ("hitl_approved", "hitl_rejected"):
            await self._handle_hitl_decision(request_id, span_id, event_type, payload)

    @staticmethod
    def _is_auth_event(event: Dict[str, Any]) -> bool:
        event_type = (event.get("event_type") or "").strip().lower()
        component = (event.get("component") or "").strip().lower()
        return component == "auth" or event_type.startswith("auth_")

    async def _persist_auth_event(self, event: Dict[str, Any]) -> None:
        payload_json = event.get("payload_json", "{}")
        try:
            payload = json.loads(payload_json)
        except Exception:
            payload = {}

        try:
            event_id = UUID(event["event_id"]) if event.get("event_id") else uuid4()
        except Exception:
            event_id = uuid4()

        event_time = self._parse_event_time(event) or datetime.now(timezone.utc)

        try:
            async with self.db.begin_nested():
                row = AuthAuditEventModel(
                    event_id=event_id,
                    tenant_id=self._resolve_tenant_id(event, payload),
                    event_time=event_time,
                    event_type=event.get("event_type") or "auth_unknown",
                    component=(event.get("component") or "auth"),
                    user_id=(event.get("actor_id") or payload.get("user_id")),
                    email=payload.get("email"),
                    actor_type=event.get("actor_type") or payload.get("actor_type"),
                    actor_id=event.get("actor_id") or payload.get("actor_id"),
                    ip_addr=payload.get("ip_addr") or payload.get("ip"),
                    user_agent=payload.get("user_agent"),
                    result=payload.get("result"),
                    reason_code=payload.get("reason_code") or payload.get("reason"),
                    payload=payload if isinstance(payload, dict) else {},
                )
                self.db.add(row)
                await self.db.flush()
        except IntegrityError:
            _LOGGER.info("Auth event %s already exists. Skip.", event.get("event_id"))
        except Exception as e:
            _LOGGER.error("Failed to persist auth event %s: %s", event.get("event_id"), e)

    @staticmethod
    def _resolve_tenant_id(event: Dict[str, Any], payload: Dict[str, Any]) -> UUID:
        settings = get_settings()
        raw = event.get("tenant_id") or payload.get("tenant_id") or settings.auth_default_tenant_id
        try:
            return UUID(str(raw))
        except Exception:
            return UUID(settings.auth_default_tenant_id)

    async def _handle_job_pause(
        self,
        request_id: UUID,
        span_id: UUID | None,
        event_time: datetime | None,
    ) -> None:
        """Mark an async job as paused (waiting for approval)."""
        ts = event_time or datetime.now(timezone.utc)

        if span_id:
            await self.db.execute(
                update(AgentSpanModel)
                .where(AgentSpanModel.span_id == span_id)
                .values(status="interrupted", ended_at=ts)
            )

        await self.db.execute(
            update(AgentRunModel)
            .where(AgentRunModel.request_id == request_id)
            .values(status="interrupted", ended_at=ts)
        )

    async def _handle_job_resume(self, request_id: UUID, span_id: UUID | None) -> None:
        """Re-open an async job after HITL resume."""
        if span_id:
            await self.db.execute(
                update(AgentSpanModel)
                .where(AgentSpanModel.span_id == span_id)
                .values(status="running", ended_at=None)
            )

        await self.db.execute(
            update(AgentRunModel)
            .where(AgentRunModel.request_id == request_id)
            .values(status="running", ended_at=None)
        )
            
    def _parse_event_time(self, event: Dict[str, Any]) -> datetime | None:
        """Parse emitter epoch seconds into a timezone-aware datetime."""
        raw = event.get("event_time") or event.get("timestamp")
        if raw in (None, ""):
            return None
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except Exception:
            return None

    async def _handle_job_phase_spans(
        self,
        *,
        request_id: UUID,
        event_type: str | None,
        event_time: datetime | None,
        session_id: str | None,
        thread_id: str | None,
        payload: Dict[str, Any],
    ) -> None:
        """Create a tiny, stable set of child spans under the job root for lifecycle phases.

        These are not emitted by LangChain; we derive them from job_* events to make the
        Timeline tree more informative without exploding node count.
        """
        if not isinstance(event_type, str):
            return

        # In async mode we enforce request_id == job_id. Use request_id as the namespace.
        job_id = request_id
        queued_span_id = uuid5(job_id, "job_phase:queued")
        exec_span_id = uuid5(job_id, "job_phase:execute")
        wait_span_id = uuid5(job_id, "job_phase:waiting_approval")

        ts = event_time or datetime.now(timezone.utc)

        async def ensure_phase(span_id: UUID, *, name: str, phase: str, status: str) -> AgentSpanModel:
            existing = await self.db.get(AgentSpanModel, span_id)
            if existing:
                # Re-open a phase span on resume.
                if status == "running":
                    existing.status = "running"
                    existing.ended_at = None
                # Keep the earliest started_at (events may arrive out-of-order).
                if existing.started_at and existing.started_at > ts:
                    existing.started_at = ts
                if not existing.node_name:
                    existing.node_name = name
                existing.status = existing.status or status
                self.db.add(existing)
                await self.db.flush()
                return existing

            span = AgentSpanModel(
                span_id=span_id,
                request_id=job_id,
                parent_span_id=job_id,
                span_type="job_phase",
                agent_name="job",
                node_name=name,
                status=status,
                started_at=ts,
                meta={
                    "phase": phase,
                    "job_id": str(job_id),
                    "session_id": session_id,
                    "thread_id": thread_id,
                },
            )
            self.db.add(span)
            await self.db.flush()
            return span

        async def close_phase(span_id: UUID, *, status: str) -> None:
            existing = await self.db.get(AgentSpanModel, span_id)
            if not existing:
                return
            # Keep the latest ended_at (events may arrive out-of-order).
            if existing.ended_at is None or existing.ended_at < ts:
                existing.ended_at = ts
            # Only overwrite "running" with a terminal status.
            if existing.status == "running" or not existing.status:
                existing.status = status
            self.db.add(existing)
            await self.db.flush()

        if event_type == "job_queued":
            await ensure_phase(queued_span_id, name="Queued", phase="queued", status="running")
            return

        if event_type == "job_started":
            await ensure_phase(queued_span_id, name="Queued", phase="queued", status="running")
            await close_phase(queued_span_id, status="succeeded")
            await ensure_phase(exec_span_id, name="Running", phase="execute", status="running")
            return

        if event_type == "job_waiting_approval":
            # Close Running as interrupted and open Waiting Approval.
            await ensure_phase(exec_span_id, name="Running", phase="execute", status="running")
            await close_phase(exec_span_id, status="interrupted")
            await ensure_phase(wait_span_id, name="Waiting Approval", phase="waiting_approval", status="running")
            return

        if event_type == "job_resumed":
            # Close Waiting Approval and re-open Running.
            await ensure_phase(wait_span_id, name="Waiting Approval", phase="waiting_approval", status="running")
            await close_phase(wait_span_id, status="succeeded")
            await ensure_phase(exec_span_id, name="Running", phase="execute", status="running")
            return

        terminal_map = {
            "job_completed": "succeeded",
            "job_failed": "failed",
            "job_cancelled": "cancelled",
            "job_timed_out": "failed",
        }
        if event_type in terminal_map:
            await ensure_phase(exec_span_id, name="Running", phase="execute", status="running")
            await close_phase(exec_span_id, status=terminal_map[event_type])

            # If the job terminates before job_started, cap the queued phase too.
            queued = await ensure_phase(queued_span_id, name="Queued", phase="queued", status="running")
            if queued.ended_at is None:
                await close_phase(queued_span_id, status=terminal_map[event_type])

            # Close Waiting Approval too (if it exists) so the phase tree is always clean.
            waiting = await self.db.get(AgentSpanModel, wait_span_id)
            if waiting and waiting.ended_at is None:
                await close_phase(wait_span_id, status=terminal_map[event_type])
            return
            
    async def _ensure_run_exists(self, request_id: UUID, session_id: str | None, thread_id: str | None, tenant_id: UUID):
        """Ensure AgentRunModel exists. Idempotent."""
        existing = await self.db.get(AgentRunModel, request_id)
        if existing:
            # Best effort linkage: some events might arrive before run_started
            # or with incomplete session/thread fields. Fill when we can.
            if session_id and (existing.conversation_id is None or existing.conversation_id == ""):
                existing.conversation_id = session_id
            if thread_id and (existing.thread_id is None or existing.thread_id == ""):
                existing.thread_id = thread_id
            if getattr(existing, "tenant_id", None) is None:
                existing.tenant_id = tenant_id
            await self.db.flush()
            return
            
        try:
             # Force INSERT via nested transaction to handle race conditions
            async with self.db.begin_nested():
                # For robustness, handle case where run might have been created by another worker
                # but not yet committed? No, consistent read.
                # Just insert.
                run = AgentRunModel(
                    request_id=request_id,
                    tenant_id=tenant_id,
                    # Best effort linkage for list/filtering in UI
                    conversation_id=session_id or None,
                    thread_id=thread_id or None,
                    started_at=datetime.now(timezone.utc),
                )
                self.db.add(run)
                await self.db.flush()
        except Exception as e:
            # Log errors (usually IntegrityError) but continue
            _LOGGER.error(f"Ensure Run {request_id} failed: {e}")
            pass

    async def _ensure_span_exists(self, request_id: UUID, span_id: UUID, session_id: str | None, thread_id: str | None):
        """Ensure AgentSpanModel exists. Idempotent."""
        existing = await self.db.get(AgentSpanModel, span_id)
        if existing:
            return
            
        try:
            async with self.db.begin_nested():
                span = AgentSpanModel(
                    span_id=span_id,
                    request_id=request_id,
                    span_type="unknown",
                    agent_name="unknown", 
                    status="running",
                    # created_at and started_at default to now
                    started_at=datetime.now(timezone.utc)
                )
                self.db.add(span)
                await self.db.flush()
        except IntegrityError:
            # Race condition: span created by another event in parallel. Safe to ignore.
            pass
        except Exception as e:
            # Log real errors
            _LOGGER.error(f"Ensure Span {span_id} failed: {e}")
            pass


    async def _handle_run_start(self, request_id: UUID, session_id: str | None, thread_id: str | None, payload: Dict[str, Any], tenant_id: UUID):
        """Create or Update AgentRunModel."""
        _LOGGER.info(f"Handling RUN START for {request_id}")
        agent_name = payload.get("root_agent_name", "unknown")
        
        # 1. Update Run Model
        existing = await self.db.get(AgentRunModel, request_id)
        if existing:
            # Ensure linkage is populated (run may have been created by _ensure_run_exists)
            if (existing.conversation_id is None or existing.conversation_id == "") and session_id:
                existing.conversation_id = session_id
            if (existing.thread_id is None or existing.thread_id == "") and thread_id:
                existing.thread_id = thread_id
            if (existing.root_agent_name is None or existing.root_agent_name == "unknown") and agent_name != "unknown":
                existing.root_agent_name = agent_name
            # Support HITL resume: a new run may start again for the same request_id.
            existing.status = "running"
            existing.ended_at = None
            if getattr(existing, "tenant_id", None) is None:
                existing.tenant_id = tenant_id
        else:
            run = AgentRunModel(
                request_id=request_id,
                tenant_id=tenant_id,
                status="running",
                conversation_id=session_id,
                thread_id=thread_id,
                root_agent_name=agent_name
            )
            self.db.add(run)
        
        await self.db.flush()
        
        # NEW ARCHITECTURE: NO FAKE ROOT SPAN
        # The first span from LangGraph will naturally be the root (parent=None).

    async def _handle_run_end(self, request_id: UUID, event_type: str, payload: Dict[str, Any]):
        """Update AgentRunModel."""
        if event_type == "run_finished":
            status = "succeeded"
        elif event_type == "run_interrupted":
            status = "interrupted"
        else:
            status = "failed"
            
        stmt = update(AgentRunModel).where(AgentRunModel.request_id == request_id)
        
        # Prevent overwriting 'interrupted' or 'failed' with 'succeeded'
        if status == "succeeded":
            stmt = stmt.where(AgentRunModel.status.not_in(["interrupted", "failed"]))

        stmt = stmt.values(
            status=status,
            ended_at=datetime.now(timezone.utc)
        )
        if status == "failed":
            stmt = stmt.values(
                error_message=payload.get("error_message"),
                error_code=payload.get("error_class")
            )
        await self.db.execute(stmt)

    async def _handle_job_end(self, request_id: UUID, event_type: str, payload: Dict[str, Any]) -> None:
        """Update AgentRunModel from job lifecycle terminal events."""
        status_map = {
            "job_completed": "succeeded",
            "job_failed": "failed",
            "job_cancelled": "cancelled",
            "job_timed_out": "failed",
        }
        status = status_map.get(event_type)
        if not status:
            return

        stmt = update(AgentRunModel).where(AgentRunModel.request_id == request_id)

        # Prevent overwriting terminal failures/cancels with success.
        if status == "succeeded":
            stmt = stmt.where(AgentRunModel.status.not_in(["interrupted", "failed", "cancelled"]))

        values: Dict[str, Any] = {
            "status": status,
            "ended_at": datetime.now(timezone.utc),
        }
        if status == "failed":
            values["error_message"] = payload.get("error_message")
            values["error_code"] = payload.get("error_class")

        await self.db.execute(stmt.values(**values))

    async def _handle_span_start(self, request_id: UUID, span_id: UUID | None, event_type: str, payload: Dict[str, Any], event: Dict[str, Any]):
        """Create AgentSpanModel."""
        if not span_id:
            return
            
        span = await self.db.get(AgentSpanModel, span_id)
        
        # If exists and NOT a placeholder, we are done (idempotent)
        if span and span.span_type != "unknown":
            # Support job resume: reopen the job root so later job_completed can mark it succeeded.
            if span.span_type == "job" and event_type in ("job_resumed", "job_started"):
                span.status = "running"
                span.ended_at = None
                self.db.add(span)
                await self.db.flush()
            return
            
        if not span:
            # Create new instance if verified not to exist
            span = AgentSpanModel(
                span_id=span_id,
                request_id=request_id
            )

        # Now populate/overwrite fields (Update Logic)
        span_type = "chain"
        if isinstance(event_type, str) and event_type.startswith("job_"):
            span_type = "job"
        if "tool" in event_type: span_type = "tool"
        elif "llm" in event_type: span_type = "llm"
        elif "node" in event_type: span_type = "node"
        elif "subagent" in event_type: span_type = "chain"
        
        # Extract meaningful names
        node_name = payload.get("name") or event.get("name")
        if span_type == "job":
            title = payload.get("title") or payload.get("job_title") or payload.get("input_message")
            node_name = f"Job: {str(title)[:120]}" if title else "Job"
        # langgraph_node_started uses "node_id" in payload
        if not node_name and "node_id" in payload:
             node_name = payload["node_id"]
        if not node_name and "langgraph_node" in payload:  
             node_name = payload["langgraph_node"]
        if not node_name and "langgraph_node" in event:
             node_name = event["langgraph_node"]
        
        subagent_kind = payload.get("subagent")
        
        # Infer context
        if (node_name == "LangGraph" or not subagent_kind) and event.get("parent_span_id"):
             try:
                 parent = await self.db.get(AgentSpanModel, UUID(event["parent_span_id"]))
                 if parent and parent.meta and parent.meta.get("tool_name") == "task":
                     digest = parent.meta.get("input_digest")
                     if digest:
                         import ast
                         try:
                             inputs = ast.literal_eval(digest)
                             if isinstance(inputs, dict) and "subagent_type" in inputs:
                                 subagent_kind = inputs["subagent_type"]
                                 if node_name == "LangGraph":
                                     node_name = subagent_kind
                         except:
                             pass
             except Exception:
                 pass

        # Resolve Parent Span ID (Native LangChain Topology)
        # NOTE: parent_span_id is a self-FK; if parent span hasn't been persisted yet
        # (events can arrive out-of-order), setting it eagerly will violate the FK.
        # We store it in meta['pending_parent_id'] and adopt later when parent exists.
        raw_parent_id = event.get("parent_span_id")
        parent_uuid = UUID(raw_parent_id) if raw_parent_id else None

        meta = dict(payload) if isinstance(payload, dict) else {}

        # job span is the logical root; do not inherit any parent pointer
        if span_type == "job":
            parent_uuid = None

        # If this is a root chain span and a job span exists for this run,
        # physically mount the root chain under the job node.
        if span_type == "chain" and parent_uuid is None:
            try:
                job_span = await self.db.get(AgentSpanModel, request_id)
                if job_span and job_span.span_type == "job":
                    meta.setdefault("raw_parent_span_id", None)
                    meta.setdefault("mounted_under_job", True)
                    meta.setdefault("job_id", str(request_id))
                    parent_uuid = request_id
            except Exception:
                pass
        if parent_uuid:
            try:
                parent = await self.db.get(AgentSpanModel, parent_uuid)
                if parent is None:
                    meta["pending_parent_id"] = str(parent_uuid)
                    parent_uuid = None
            except Exception:
                meta["pending_parent_id"] = str(parent_uuid)
                parent_uuid = None
        
        # Apply values to model
        span.span_type = span_type
        span.agent_name = event.get("component")
        span.node_name = node_name
        span.subagent_kind = subagent_kind
        span.parent_span_id = parent_uuid
        span.meta = meta
        span.status = "running"
        
        # Add to session
        self.db.add(span)

        # Flush
        await self.db.flush()
        
        # Adopt orphans
        await self._adopt_orphans(span_id)

        # For job spans, mount any pre-existing root chain spans under this job.
        if span_type == "job":
            await self._mount_chain_roots_under_job(request_id)

    async def _adopt_orphans(self, span_id: UUID):
        """Link any existing spans that were waiting for this span_id."""
        # Update children where meta['pending_parent_id'] matches span_id
        # And clear the pending_parent_id field
        try:
             # Simpler: Just update parent_span_id. We can leave pending_parent_id there as history or clear it.
             # Ideally clear it.
             # Trying: meta = AgentSpanModel.meta - 'pending_parent_id'
             stmt = update(AgentSpanModel).where(
                 AgentSpanModel.meta['pending_parent_id'].astext == str(span_id)
             ).values(
                 parent_span_id=span_id
                 # keeping meta as is for safety/simplicity to avoid JSONB syntax errors blindly
             )
             result = await self.db.execute(stmt)
             if result.rowcount > 0:
                 _LOGGER.info(f"Span {span_id} adopted {result.rowcount} orphans.")
        except Exception as e:
             _LOGGER.warning(f"Adoption failed for {span_id}: {e}")

    async def _mount_chain_roots_under_job(self, request_id: UUID) -> None:
        """Mount pre-existing root chain spans under the synthetic job span.

        For async jobs, we create a synthetic root span with:
            span_id == request_id
            span_type == "job"

        LangChain root chain spans may arrive before the job_* events (out-of-order).
        This helper rewires those chain roots (parent_span_id IS NULL) to be children
        of the job span so the UI shows a single rooted tree.
        """
        try:
            job_span = await self.db.get(AgentSpanModel, request_id)
            if not job_span or job_span.span_type != "job":
                return

            stmt = (
                select(AgentSpanModel)
                .where(AgentSpanModel.request_id == request_id)
                .where(AgentSpanModel.span_type == "chain")
                .where(AgentSpanModel.parent_span_id.is_(None))
                .where(AgentSpanModel.span_id != request_id)
                .order_by(AgentSpanModel.started_at.asc())
            )
            res = await self.db.execute(stmt)
            roots = res.scalars().all()
            if not roots:
                return

            mounted = 0
            for span in roots:
                meta = dict(span.meta) if isinstance(span.meta, dict) else {}
                # If this isn't a real root (waiting for parent), don't mount it.
                if meta.get("pending_parent_id"):
                    continue
                if meta.get("mounted_under_job"):
                    continue

                meta.setdefault("raw_parent_span_id", None)
                meta["mounted_under_job"] = True
                meta["job_id"] = str(request_id)

                span.parent_span_id = request_id
                span.meta = meta
                self.db.add(span)
                mounted += 1

            if mounted:
                await self.db.flush()
                _LOGGER.info(f"Mounted {mounted} root chain span(s) under job {request_id}")
        except Exception as e:
            _LOGGER.warning(f"Mount chain roots under job failed for {request_id}: {e}")

    async def _handle_span_end(self, request_id: UUID, span_id: UUID | None, event_type: str, payload: Dict[str, Any]):
        """Update AgentSpanModel."""
        if not span_id:
            return

        job_status_map = {
            "job_completed": "succeeded",
            "job_failed": "failed",
            "job_cancelled": "cancelled",
            "job_timed_out": "failed",
        }
        if event_type in job_status_map:
            status = job_status_map[event_type]
        elif "failed" in event_type:
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
            ended_at=datetime.now(timezone.utc)
        )
        await self.db.execute(stmt)
        
        # Propagate interruption to parents
        if status == "interrupted":
            await self._propagate_interruption(span_id)

        # Reconcile Run status from Root Span status.
        # This makes run state robust even if run_finished/run_failed events are not emitted
        # (e.g., missing tags / misclassified root chain).
        await self._reconcile_run_from_root_span(request_id)

    async def _reconcile_run_from_root_span(self, request_id: UUID) -> None:
        """Best-effort run status update based on the root chain span (parent_span_id is NULL)."""
        run = await self.db.get(AgentRunModel, request_id)
        if not run:
            return

        # Only attempt to reconcile if the run isn't already in a terminal error state.
        if run.status not in ("running", "succeeded"):
            return

        root_stmt = (
            select(AgentSpanModel.status, AgentSpanModel.ended_at)
            .where(AgentSpanModel.request_id == request_id)
            .where(AgentSpanModel.parent_span_id.is_(None))
            .where(AgentSpanModel.span_type == "chain")
            .order_by(AgentSpanModel.started_at.asc())
            .limit(1)
        )
        res = await self.db.execute(root_stmt)
        root = res.first()
        if not root:
            return

        root_status, root_ended_at = root
        if root_status == "running":
            return

        status_map = {
            "succeeded": "succeeded",
            "failed": "failed",
            "interrupted": "interrupted",
        }
        target_status = status_map.get(root_status)
        if not target_status:
            return

        # Do not overwrite failed/interrupted with succeeded.
        if target_status == "succeeded" and run.status != "running":
            return

        # Allow overwriting "running/succeeded" with "failed/interrupted".
        if target_status in ("failed", "interrupted") and run.status not in ("running", "succeeded"):
            return

        stmt = update(AgentRunModel).where(AgentRunModel.request_id == request_id)
        if target_status == "succeeded":
            stmt = stmt.where(AgentRunModel.status.not_in(["interrupted", "failed"]))
        stmt = stmt.values(
            status=target_status,
            ended_at=run.ended_at or root_ended_at or datetime.now(timezone.utc),
        )
        await self.db.execute(stmt)

    async def _propagate_interruption(self, start_span_id: UUID):
        """Recursively mark active parent spans as interrupted."""
        current_id = start_span_id
        # Safety limit for recursion
        for _ in range(20): 
            # Get parent of current
            stmt = select(AgentSpanModel.parent_span_id).where(AgentSpanModel.span_id == current_id)
            res = await self.db.execute(stmt)
            parent_id = res.scalar_one_or_none()
            
            if not parent_id:
                break
                
            # Update parent status
            # Only update if running to avoid clobbering other terminal states or unrelated failures
            update_stmt = (
                update(AgentSpanModel)
                .where(AgentSpanModel.span_id == parent_id)
                .where(AgentSpanModel.status == "running") 
                .values(status="interrupted", ended_at=datetime.now(timezone.utc))
            )
            await self.db.execute(update_stmt)
            
            current_id = parent_id

    async def _handle_tool_audit(self, request_id: UUID, span_id: UUID | None, event_type: str, payload: Dict[str, Any], session_id: str | None, thread_id: str | None):
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
            request_id=request_id,
            span_id=span_id,
            session_id=session_id,
            thread_id=thread_id,
            tool_name=tool_name, 
            tool_version="1.0",
            request_time=datetime.now(timezone.utc), 
            response_time=datetime.now(timezone.utc),
            status="failed" if "failed" in event_type else "succeeded",
            output_digest=payload.get("output_digest"),
            error=payload if "failed" in event_type else None,
            side_effect_level="read" # Default
        )
        self.db.add(tool_audit)

    async def _handle_hitl_request(self, request_id: UUID, span_id: UUID | None, payload: Dict[str, Any]):
        """Create ApprovalRequestModel."""
        from uuid import uuid4
        
        # Determine risk level or action type from payload
        action_type = payload.get("tool_name", "unknown")
        
        req = ApprovalRequestModel(
            approval_id=uuid4(),
            request_id=request_id,
            span_id=span_id,
            requested_at=datetime.now(timezone.utc),
            action_type=action_type,
            risk_level="high", # Default for now
            status="pending",
            # proposed_action_blob_id we might skip or store simple payload
        )
        self.db.add(req)

    async def _handle_hitl_decision(self, request_id: UUID, span_id: UUID | None, event_type: str, payload: Dict[str, Any]):
        """Create ApprovalDecisionModel and update Request."""
        from uuid import uuid4
        
        # Find pending request
        stmt = select(ApprovalRequestModel).where(
            ApprovalRequestModel.request_id == request_id,
            ApprovalRequestModel.status == "pending"
        ).order_by(ApprovalRequestModel.requested_at.desc()).limit(1)
        
        res = await self.db.execute(stmt)
        req = res.scalar_one_or_none()
        
        if not req:
            _LOGGER.warning(f"Received HITL decision but no pending request found for request_id={request_id}")
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
            decided_at=datetime.now(timezone.utc),
            decider_id=payload.get("actor_id", "user"), # or from payload
            decision=decision_val,
            reason=payload.get("reason", "")
        )
        self.db.add(decision)
