import json
import logging
import traceback
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..models.db_models import SessionModel, AgentModel
from ..core.agent_registry import registry
from ..utils.stream_parser import QwenStreamParser
from langchain_core.messages import HumanMessage, ToolMessage

router = APIRouter(prefix="/sessions", tags=["chat"])
_LOGGER = logging.getLogger(__name__)

async def event_generator(graph, inputs: dict, config: dict) -> AsyncGenerator[str, None]:
    """Generate SSE events from LangGraph stream.
    
    Uses QwenStreamParser to parse <think>...</think> tags from Qwen model output,
    separating reasoning content from regular content.
    
    Emits: [msg_data, metadata] tuples as SSE data events.
    """
    
    # Per-subgraph parsers (isolate buffer state between agents)
    subgraph_parsers: dict = {}
    
    # Tool call accumulator for streaming chunks
    tool_call_accumulators: dict = {}
    emitted_tool_call_ids: set = set()
    
    try:
        # Stream with subgraphs=True: yields (namespace, (msg, metadata))
        async for chunk in graph.astream(inputs, config=config, stream_mode="messages", subgraphs=True):
            # Unpack chunk: (namespace, (msg, metadata))
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
                _LOGGER.warning(f"Unexpected chunk format: {type(chunk)}")
                continue
            
            try:
                # Serialize message to dict
                msg_data = msg.dict()
                msg_type = msg_data.get('type', type(msg).__name__)
                is_ai_message = msg_type in ['ai', 'AIMessageChunk', 'AIMessage']
                
                # 从 metadata 获取节点信息
                langgraph_node = metadata.get('langgraph_node', '') if isinstance(metadata, dict) else ''
                
                # 跳过 format_output 节点的 AIMessage（避免与 ToolMessage 重复）
                # SubAgent 的 format_output 返回的 AIMessage 会被框架读取并作为 ToolMessage 发送
                if is_ai_message and langgraph_node == 'format_output':
                    continue
                
                # Remove incomplete tool_calls from LangChain serialization
                if 'tool_calls' in msg_data:
                    del msg_data['tool_calls']
                
                # ToolMessage: 直接发送，不做内容处理，前端会单独处理为 tool_output
                is_tool_message = msg_type in ['tool', 'ToolMessage']
                
                content = msg_data.get('content', '')
                
                # Normalize array content to string (LangChain structured format)
                # Format: [{'type': 'text', 'text': '...'}, {'type': 'tool_call_chunk', ...}]
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
                
                # Only apply parser to AI messages (skip ToolMessage)
                if is_ai_message and not is_tool_message and isinstance(content, str) and content:
                    # Get or create per-subgraph parser
                    sg_key = subgraph_name or "__main__"
                    if sg_key not in subgraph_parsers:
                        subgraph_parsers[sg_key] = QwenStreamParser()
                    parser = subgraph_parsers[sg_key]
                    
                    # Use parser to process content
                    events = parser._parse_tags(content)
                    
                    # Accumulate parsed content and reasoning from events
                    parsed_content = ""
                    parsed_reasoning = ""
                    for event in events:
                        if event["type"] == "content":
                            parsed_content += event["data"]
                        elif event["type"] == "thinking":
                            parsed_reasoning += event["data"]
                    
                    # Update msg_data with parsed content
                    msg_data['content'] = parsed_content
                    
                    if parsed_reasoning:
                        if 'additional_kwargs' not in msg_data:
                            msg_data['additional_kwargs'] = {}
                        msg_data['additional_kwargs']['reasoning_content'] = parsed_reasoning
                
                # Accumulate tool_call_chunks
                if msg_data.get('tool_call_chunks'):
                    for chunk in msg_data['tool_call_chunks']:
                        chunk_index = chunk.get('index', 0)
                        chunk_name = chunk.get('name')
                        chunk_args = chunk.get('args') or ''
                        chunk_id = chunk.get('id')
                        
                        key = f"{chunk_index}"
                        if chunk_name:
                            # New tool call starting
                            tool_call_accumulators[key] = {
                                'name': chunk_name,
                                'args_str': chunk_args,
                                'id': chunk_id or '',
                                'subgraph': subgraph_name
                            }
                        elif key in tool_call_accumulators:
                            # Continue accumulating args
                            tool_call_accumulators[key]['args_str'] += chunk_args
                            if chunk_id:
                                tool_call_accumulators[key]['id'] = chunk_id
                    
                    # Just accumulate, don't emit yet - will emit when no more chunks
                else:
                    # No tool_call_chunks in this message - check if we have accumulated tool_calls to emit
                    for key, acc in list(tool_call_accumulators.items()):
                        if acc.get('id') and acc['id'] not in emitted_tool_call_ids:
                            try:
                                parsed_args = json.loads(acc['args_str']) if acc['args_str'] else {}
                                emitted_tool_call_ids.add(acc['id'])
                                
                                # Add completed tool_call to msg_data
                                if 'tool_calls' not in msg_data:
                                    msg_data['tool_calls'] = []
                                msg_data['tool_calls'].append({
                                    'id': acc['id'],
                                    'name': acc['name'],
                                    'args': parsed_args
                                })
                                del tool_call_accumulators[key]
                            except json.JSONDecodeError:
                                # Args still not valid JSON, keep waiting
                                pass
                
                payload = [msg_data, metadata]
                yield f"data: {json.dumps(payload)}\n\n"
                
            
            except Exception as e:
                _LOGGER.error(f"Failed to serialize tuple payload: {e}")
                _LOGGER.error(traceback.format_exc())
                continue
        
        # Flush any remaining buffer content from all parsers
        for sg_key, parser in subgraph_parsers.items():
            flush_events = parser.flush()
            for event in flush_events:
                if event["type"] == "thinking":
                    flush_data = {"type": "AIMessageChunk", "content": "", "additional_kwargs": {"reasoning_content": event["data"]}}
                else:
                    flush_data = {"type": "AIMessageChunk", "content": event["data"]}
                yield f"data: {json.dumps([flush_data, {'subgraph': sg_key}])}\n\n"
        
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        yield ": keep-alive\n\n"

    except Exception as e:
        _LOGGER.error(f"Stream error: {e}")
        _LOGGER.error(traceback.format_exc())
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

@router.post("/{session_id}/chat")
async def chat_stream(
    session_id: str,
    message: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream chat response using SSE.
    """
    # Load Session + Agent
    stmt = select(SessionModel).options(selectinload(SessionModel.agent)).where(SessionModel.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Get Plugin
    agent_key = session.agent.builtin_key
    if not agent_key or not registry.get_plugin(agent_key):
        raise HTTPException(status_code=500, detail=f"Agent plugin '{agent_key}' not loaded")
        
    plugin = registry.get_plugin(agent_key)
    graph = plugin.get_graph()
    
    # Config for LangGraph (Checkpointer uses thread_id)
    config = {
        "configurable": {
            "thread_id": str(session.id),
            "user_id": "mock_user", # TODO: Get from auth
            "analysis_id": str(session.id) # Re-use session ID for now
        }
    }

    inputs = {"messages": [HumanMessage(content=message)]}
    return StreamingResponse(
        event_generator(graph, inputs, config),
        media_type="text/event-stream"
    )
