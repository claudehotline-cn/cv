import json
import logging
import traceback
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..models.db_models import SessionModel, AgentModel
from ..core.agent_registry import registry
from ..utils.stream_parser import QwenStreamParser
from langchain_core.messages import HumanMessage, ToolMessage
from agent_core.events import RedisEventBus, AuditEmitter
from agent_core.settings import get_settings
from agent_core.audit import AuditCallbackHandler
from ..utils.interrupts import extract_interrupt_data
from ..utils.session_memory import extract_recent_messages

router = APIRouter(prefix="/sessions", tags=["chat"])
_LOGGER = logging.getLogger(__name__)

async def event_generator(graph, inputs: dict, config: dict) -> AsyncGenerator[str, None]:
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

@router.post("/{session_id}/chat")
async def chat_stream(
    session_id: str,
    request: Request,
    message: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(SessionModel).options(selectinload(SessionModel.agent)).where(SessionModel.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    agent_key = session.agent.builtin_key
    if not agent_key or not registry.get_plugin(agent_key):
        raise HTTPException(status_code=500, detail=f"Agent plugin '{agent_key}' not loaded")
        
    plugin = registry.get_plugin(agent_key)
    graph = plugin.get_graph()
    
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
        "user_id": "mock_user",
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
            "agent_key": agent_key,
            "agent_id": str(session.agent.id),
            "agent_name": session.agent.name,
        },
    }
    config["audit_emitter"] = emitter

    inputs = {"messages": [HumanMessage(content=message)]}
    return StreamingResponse(
        event_generator(graph, inputs, config),
        media_type="text/event-stream"
    )


class ResumeRequest(BaseModel):
    decision: str 
    feedback: str = ""

@router.post("/{session_id}/resume")
async def resume_chat(
    session_id: str,
    request: ResumeRequest,
    db: AsyncSession = Depends(get_db)
):
    from langgraph.types import Command
    
    stmt = select(SessionModel).options(selectinload(SessionModel.agent)).where(SessionModel.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    agent_key = session.agent.builtin_key
    if not agent_key or not registry.get_plugin(agent_key):
        raise HTTPException(status_code=500, detail=f"Agent plugin '{agent_key}' not loaded")
        
    plugin = registry.get_plugin(agent_key)
    graph = plugin.get_graph()
    
    thread_id = str(session.thread_id) if session.thread_id else str(session.id)
    configurable = {
        "thread_id": thread_id,
        "session_id": str(session.id),
        "user_id": "mock_user",
    }
    if agent_key == "data_agent":
        configurable["analysis_id"] = str(session.id)

    config = {"configurable": configurable}

    decisions = [{"type": request.decision, "message": request.feedback}]
    resume_input = Command(resume=decisions)
    
    return StreamingResponse(
        event_generator(graph, resume_input, config),
        media_type="text/event-stream"
    )
