import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from uuid import UUID

from ..db import get_db
from ..models.db_models import SessionModel, AgentVersionModel
from ..core.agent_registry import registry
from ..utils.stream_parser import QwenStreamParser
from langchain_core.messages import HumanMessage
from agent_core.events import AuditEmitter
from agent_core.audit import AuditCallbackHandler
from ..utils.interrupts import extract_interrupt_data
from ..utils.session_memory import extract_recent_messages
from ..core.auth import AuthPrincipal, get_current_user
from ..platform_core.policy import PolicyDecision
from ..services.tenant_shadow_service import TenantShadowService

router = APIRouter(prefix="/sessions", tags=["chat"])
_LOGGER = logging.getLogger(__name__)


class _NoopSemanticCache:
    async def lookup(self, _key: Any) -> None:
        return None

    async def store(self, _key: Any, _value: Any) -> None:
        return None


class _NoopSpan:
    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool:
        return False


class _NoopTelemetry:
    def start_span(self, _name: str, attributes: dict[str, str] | None = None) -> _NoopSpan:
        _ = attributes
        return _NoopSpan()

    def increment(self, _name: str, value: int = 1, attributes: dict[str, str] | None = None) -> None:
        _ = (value, attributes)


@dataclass
class _Phase2ExecuteContext:
    telemetry: Any
    semantic_cache: Any
    pre_input_check: Any = None
    post_output_check: Any = None
    cacheable: bool | None = False


@dataclass
class _Phase2Request:
    tenant_id: str | None
    namespace: str
    model_key: str
    query_text: str


async def _run_with_phase2_orchestrator(
    *,
    orchestrator: Callable[[Any, Any, Callable[[Any], Awaitable[dict[str, Any]]]], Awaitable[dict[str, Any]]],
    telemetry: Any,
    tenant_id: str | None,
    namespace: str,
    model_key: str,
    query_text: str,
    executor: Callable[[Any], Awaitable[dict[str, Any]]],
    guardrails: Any | None = None,
    semantic_cache: Any | None = None,
) -> dict[str, Any]:
    request_model = _Phase2Request(
        tenant_id=tenant_id,
        namespace=namespace,
        model_key=model_key,
        query_text=query_text,
    )

    async def _pre_input_check(request: Any, _ctx: Any) -> PolicyDecision:
        if guardrails is None:
            return PolicyDecision(action="allow")
        decision = await guardrails.evaluate_input(
            tenant_id=request.tenant_id,
            text=request.query_text,
        )
        action = str(getattr(decision, "action", "allow") or "allow")
        if action == "require_approval":
            action = "block"
        if action == "block":
            return PolicyDecision(
                action="block",
                reason_code=getattr(decision, "reason_code", None),
                payload=getattr(decision, "payload", None),
            )
        if action == "redact":
            return PolicyDecision(
                action="redact",
                reason_code=getattr(decision, "reason_code", None),
                payload=getattr(decision, "payload", None),
            )
        return PolicyDecision(
            action="allow",
            reason_code=getattr(decision, "reason_code", None),
            payload=getattr(decision, "payload", None),
        )

    async def _post_output_check(request: Any, payload: dict[str, Any], _ctx: Any) -> PolicyDecision:
        if guardrails is None:
            return PolicyDecision(action="allow")
        decision = await guardrails.evaluate_output(
            tenant_id=request.tenant_id,
            text=str(payload),
        )
        action = str(getattr(decision, "action", "allow") or "allow")
        if action == "require_approval":
            action = "block"
        if action == "block":
            return PolicyDecision(
                action="block",
                reason_code=getattr(decision, "reason_code", None),
                payload=getattr(decision, "payload", None),
            )
        if action == "redact":
            sanitized_text = getattr(decision, "sanitized_text", None)
            sanitized_payload = None
            if isinstance(sanitized_text, str):
                sanitized_payload = dict(payload)
                if "answer" in sanitized_payload:
                    sanitized_payload["answer"] = sanitized_text
                else:
                    sanitized_payload["content"] = sanitized_text
            return PolicyDecision(
                action="redact",
                reason_code=getattr(decision, "reason_code", None),
                payload=getattr(decision, "payload", None),
                sanitized_payload=sanitized_payload,
            )
        return PolicyDecision(
            action="allow",
            reason_code=getattr(decision, "reason_code", None),
            payload=getattr(decision, "payload", None),
        )

    result = await orchestrator(
        request_model,
        _Phase2ExecuteContext(
            telemetry=telemetry or _NoopTelemetry(),
            semantic_cache=semantic_cache or _NoopSemanticCache(),
            pre_input_check=_pre_input_check,
            post_output_check=_post_output_check,
        ),
        executor,
    )
    status = result.get("status")
    if status == "blocked":
        raise HTTPException(
            status_code=403,
            detail={
                "detail": "orchestrator_blocked",
                "reason_code": result.get("reason_code"),
            },
        )
    payload = result.get("payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Invalid orchestrator payload")
    return payload


async def event_generator(graph, inputs: Any, config: dict[str, Any]) -> AsyncGenerator[str, None]:
    """Generate SSE events from LangGraph stream."""
    
    subgraph_parsers: dict = {}
    tool_call_accumulators: dict = {}
    emitted_tool_call_ids: set = set()
    
    try:
        async for chunk in graph.astream(inputs, config=config, stream_mode="messages", subgraphs=True):
            subgraph_name = None
            if isinstance(chunk, tuple) and len(chunk) == 2:
                namespace, inner = chunk
                if isinstance(inner, tuple) and len(inner) == 2:
                    msg, metadata = inner
                    if namespace:
                        subgraph_name = namespace[-1] if namespace else None
                else:
                    msg, metadata = chunk
            else:
                continue
            
            try:
                msg_data = msg.dict()
                msg_type = msg_data.get('type', type(msg).__name__)
                is_ai_message = msg_type in ['ai', 'AIMessageChunk', 'AIMessage']
                
                langgraph_node = metadata.get('langgraph_node', '') if isinstance(metadata, dict) else ''
                
                if is_ai_message and langgraph_node == 'format_output':
                    continue
                
                if 'tool_calls' in msg_data:
                    del msg_data['tool_calls']
                
                is_tool_message = msg_type in ['tool', 'ToolMessage']
                content = msg_data.get('content', '')
                
                original_has_chunks = 'tool_call_chunks' in msg_data and msg_data['tool_call_chunks']
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict):
                            if block.get('type') == 'text':
                                text_parts.append(block.get('text', ''))
                            elif block.get('type') == 'tool_call_chunk' and not original_has_chunks:
                                if 'tool_call_chunks' not in msg_data:
                                    msg_data['tool_call_chunks'] = []
                                msg_data['tool_call_chunks'].append({
                                    'index': block.get('index', 0),
                                    'name': block.get('name'),
                                    'args': block.get('args') or '',
                                    'id': block.get('id')
                                })
                    content = ''.join(text_parts)
                    msg_data['content'] = content
                
                if is_ai_message and not is_tool_message and isinstance(content, str) and content:
                    sg_key = subgraph_name or "__main__"
                    if sg_key not in subgraph_parsers:
                        subgraph_parsers[sg_key] = QwenStreamParser()
                    parser = subgraph_parsers[sg_key]
                    
                    events = parser._parse_tags(content)
                    parsed_content = ""
                    parsed_reasoning = ""
                    for event in events:
                        if event["type"] == "content":
                            parsed_content += event["data"]
                        elif event["type"] == "thinking":
                            parsed_reasoning += event["data"]
                    
                    msg_data['content'] = parsed_content
                    if parsed_reasoning:
                        if 'additional_kwargs' not in msg_data:
                            msg_data['additional_kwargs'] = {}
                        msg_data['additional_kwargs']['reasoning_content'] = parsed_reasoning
                
                if msg_data.get('tool_call_chunks'):
                    for chunk in msg_data['tool_call_chunks']:
                        chunk_index = chunk.get('index', 0)
                        chunk_name = chunk.get('name')
                        chunk_args = chunk.get('args') or ''
                        chunk_id = chunk.get('id')
                        
                        key = f"{chunk_index}"
                        if chunk_name:
                            tool_call_accumulators[key] = {
                                'name': chunk_name,
                                'args_str': chunk_args,
                                'id': chunk_id or '',
                                'subgraph': subgraph_name
                            }
                        elif key in tool_call_accumulators:
                            tool_call_accumulators[key]['args_str'] += chunk_args
                            if chunk_id:
                                tool_call_accumulators[key]['id'] = chunk_id
                else:
                    for key, acc in list(tool_call_accumulators.items()):
                        if acc.get('id') and acc['id'] not in emitted_tool_call_ids:
                            try:
                                parsed_args = json.loads(acc['args_str']) if acc['args_str'] else {}
                                emitted_tool_call_ids.add(acc['id'])
                                if 'tool_calls' not in msg_data:
                                    msg_data['tool_calls'] = []
                                msg_data['tool_calls'].append({
                                    'id': acc['id'],
                                    'name': acc['name'],
                                    'args': parsed_args
                                })
                                del tool_call_accumulators[key]
                            except json.JSONDecodeError:
                                pass
                
                has_content = bool(msg_data.get('content'))
                has_reasoning = bool(msg_data.get('additional_kwargs', {}).get('reasoning_content'))
                has_tool_chunks = bool(msg_data.get('tool_call_chunks'))
                has_tool_calls = bool(msg_data.get('tool_calls'))
                
                if not (has_content or has_reasoning or has_tool_chunks or has_tool_calls):
                    continue

                payload = [msg_data, metadata]
                yield f"data: {json.dumps(payload)}\n\n"
            
            except Exception as e:
                _LOGGER.error(f"Failed to serialize tuple payload: {e}")
                continue
        
        for sg_key, parser in subgraph_parsers.items():
            flush_events = parser.flush()
            for event in flush_events:
                if event["type"] == "thinking":
                    flush_data = {"type": "AIMessageChunk", "content": "", "additional_kwargs": {"reasoning_content": event["data"]}}
                else:
                    flush_data = {"type": "AIMessageChunk", "content": event["data"]}
                yield f"data: {json.dumps([flush_data, {'subgraph': sg_key}])}\n\n"
        
        try:
            state = await graph.aget_state(config)
            interrupt_data = extract_interrupt_data(state)
            if interrupt_data is not None:
                yield f"data: {json.dumps({'type': 'interrupt', '__interrupt__': interrupt_data})}\n\n"

            # Persist a small, session-scoped "shared memory" snapshot for async jobs.
            try:
                from agent_core.store import get_async_store

                session_key = (
                    config.get("metadata", {}) or {}
                ).get("session_id") or (config.get("configurable", {}) or {}).get("session_id")
                if session_key:
                    recent = extract_recent_messages(state, limit=12)
                    if recent:
                        store = await get_async_store()
                        await store.aput(
                            ("agent_platform", "sessions", str(session_key)),
                            "recent_messages",
                            {"messages": recent},
                        )
            except Exception:
                pass
        except Exception:
            pass
        
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        yield ": keep-alive\n\n"

    except Exception as e:
        import traceback
        _LOGGER.error(f"Stream error: {e}\n{traceback.format_exc()}")
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

def _tenant_uuid_or_401(user: AuthPrincipal) -> UUID:
    tenant_id = (user.tenant_id or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant context required")
    try:
        return UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant context") from exc


def _session_owner_user_id(session: SessionModel) -> str | None:
    if session.user_id:
        return session.user_id
    state = session.state if isinstance(session.state, dict) else {}
    owner = state.get("owner_user_id")
    return str(owner) if owner else None


async def _get_owned_session_or_404(
    db: AsyncSession,
    *,
    session_id: str,
    user: AuthPrincipal,
) -> SessionModel:
    tenant_uuid = _tenant_uuid_or_401(user)
    if not await TenantShadowService(db).has_active_membership(tenant_uuid, user.user_id):
        raise HTTPException(status_code=403, detail="Tenant membership required")

    stmt = (
        select(SessionModel)
        .options(selectinload(SessionModel.agent))
        .where(
            SessionModel.id == session_id,
            SessionModel.tenant_id == tenant_uuid,
        )
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if user.role != "admin":
        owner_user_id = _session_owner_user_id(session)
        if not owner_user_id or owner_user_id != user.user_id:
            raise HTTPException(status_code=404, detail="Session not found")

    return session


@router.post("/{session_id}/chat")
async def chat_stream(
    session_id: str,
    request: Request,
    message: str = Body(..., embed=True),
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    session = await _get_owned_session_or_404(db, session_id=session_id, user=user)
        
    agent_key = session.agent.builtin_key
    if not agent_key or not registry.get_plugin(agent_key):
        raise HTTPException(status_code=500, detail=f"Agent plugin '{agent_key}' not loaded")
        
    plugin = registry.get_plugin(agent_key)
    if plugin is None:
        raise HTTPException(status_code=500, detail=f"Agent plugin '{agent_key}' not loaded")
    graph = plugin.get_graph()

    # Resolve agent config: prefer published version, fallback to agents.config
    agent_config = session.agent.config
    if session.agent.published_version_id:
        pub_ver = await db.get(AgentVersionModel, session.agent.published_version_id)
        if pub_ver:
            agent_config = pub_ver.config

    # Use global event bus to avoid event loop conflicts
    event_bus = request.app.state.event_bus
    
    # Audit Emitter
    emitter = AuditEmitter(redis=event_bus.redis)
    audit_callback = AuditCallbackHandler(emitter=emitter)

    import uuid
    request_id = str(uuid.uuid4())

    thread_id = str(session.thread_id) if session.thread_id else str(session.id)
    
    configurable = {
        "thread_id": thread_id,
        "session_id": str(session.id),
        "user_id": user.user_id,
    }
    # 仅 data_agent 使用 analysis_id 作为工作区隔离标识
    if agent_key == "data_agent":
        configurable["analysis_id"] = str(session.id)

    config = {
        "configurable": configurable,
        "callbacks": [audit_callback],
        "tags": [agent_key, "agent_platform"],
        "metadata": {
            "request_id": request_id,
            "session_id": str(session.id),
            "thread_id": thread_id,
            "user_id": user.user_id,
            "user_role": user.role,
            "agent_key": agent_key,
            "agent_id": str(session.agent.id),
            "agent_name": session.agent.name,
            "agent_config": agent_config,
        },
    }
    config["audit_emitter"] = emitter

    inputs = {"messages": [HumanMessage(content=message)]}

    phase2 = request.app.state.phase2
    phase2_guardrails = getattr(phase2, "guardrails", None)
    phase2_semantic_cache = getattr(phase2, "semantic_cache", None)

    async def _executor(_ctx: Any) -> dict[str, Any]:
        return {
            "graph": graph,
            "inputs": inputs,
            "config": config,
        }

    orchestrated = await _run_with_phase2_orchestrator(
        orchestrator=request.app.state.phase2.orchestrator,
        telemetry=phase2.telemetry,
        guardrails=phase2_guardrails,
        semantic_cache=phase2_semantic_cache,
        tenant_id=user.tenant_id,
        namespace="chat.stream",
        model_key=agent_key,
        query_text=message,
        executor=_executor,
    )

    graph_to_run = orchestrated.get("graph")
    inputs_to_run = orchestrated.get("inputs")
    config_to_run = orchestrated.get("config")
    if graph_to_run is None or config_to_run is None:
        raise HTTPException(status_code=500, detail="Invalid orchestrator payload")

    return StreamingResponse(
        event_generator(graph_to_run, inputs_to_run or inputs, config_to_run),
        media_type="text/event-stream"
    )


class ResumeRequest(BaseModel):
    decision: str 
    feedback: str = ""

@router.post("/{session_id}/resume")
async def resume_chat(
    session_id: str,
    request: ResumeRequest,
    http_request: Request,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    from langgraph.types import Command

    session = await _get_owned_session_or_404(db, session_id=session_id, user=user)
        
    agent_key = session.agent.builtin_key
    if not agent_key or not registry.get_plugin(agent_key):
        raise HTTPException(status_code=500, detail=f"Agent plugin '{agent_key}' not loaded")
        
    plugin = registry.get_plugin(agent_key)
    if plugin is None:
        raise HTTPException(status_code=500, detail=f"Agent plugin '{agent_key}' not loaded")
    graph = plugin.get_graph()

    # Resolve agent config: prefer published version, fallback to agents.config
    agent_config = session.agent.config
    if session.agent.published_version_id:
        pub_ver = await db.get(AgentVersionModel, session.agent.published_version_id)
        if pub_ver:
            agent_config = pub_ver.config

    # Use global event bus for audit
    event_bus = http_request.app.state.event_bus

    # Audit Emitter
    emitter = AuditEmitter(redis=event_bus.redis)
    audit_callback = AuditCallbackHandler(emitter=emitter)

    import uuid
    request_id = str(uuid.uuid4())

    thread_id = str(session.thread_id) if session.thread_id else str(session.id)
    configurable = {
        "thread_id": thread_id,
        "session_id": str(session.id),
        "user_id": user.user_id,
    }
    if agent_key == "data_agent":
        configurable["analysis_id"] = str(session.id)

    config = {
        "configurable": configurable,
        "callbacks": [audit_callback],
        "tags": [agent_key, "agent_platform"],
        "metadata": {
            "request_id": request_id,
            "session_id": str(session.id),
            "thread_id": thread_id,
            "user_id": user.user_id,
            "user_role": user.role,
            "agent_key": agent_key,
            "agent_id": str(session.agent.id),
            "agent_name": session.agent.name,
            "agent_config": agent_config,
        },
    }
    config["audit_emitter"] = emitter

    decisions = [{"type": request.decision, "message": request.feedback}]
    resume_input = Command(resume=decisions)

    phase2 = http_request.app.state.phase2
    phase2_guardrails = getattr(phase2, "guardrails", None)
    phase2_semantic_cache = getattr(phase2, "semantic_cache", None)

    async def _executor(_ctx: Any) -> dict[str, Any]:
        return {
            "graph": graph,
            "inputs": resume_input,
            "config": config,
        }

    orchestrated = await _run_with_phase2_orchestrator(
        orchestrator=http_request.app.state.phase2.orchestrator,
        telemetry=phase2.telemetry,
        guardrails=phase2_guardrails,
        semantic_cache=phase2_semantic_cache,
        tenant_id=user.tenant_id,
        namespace="chat.resume",
        model_key=agent_key,
        query_text=f"{request.decision}\n{request.feedback}",
        executor=_executor,
    )

    graph_to_run = orchestrated.get("graph")
    inputs_to_run = orchestrated.get("inputs")
    config_to_run = orchestrated.get("config")
    if graph_to_run is None or config_to_run is None:
        raise HTTPException(status_code=500, detail="Invalid orchestrator payload")

    return StreamingResponse(
        event_generator(graph_to_run, inputs_to_run or resume_input, config_to_run),
        media_type="text/event-stream"
    )
