import json
import logging
import re
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
from langchain_core.messages import HumanMessage, ToolMessage

router = APIRouter(prefix="/sessions", tags=["chat"])
_LOGGER = logging.getLogger(__name__)

# Compiled regex for tag stripping
_THINK_TAG_RE = re.compile(r'</?think>')
_TOOL_TAG_RE = re.compile(r'</?tool_call>')

async def event_generator(graph, inputs: dict, config: dict) -> AsyncGenerator[str, None]:
    """Generate SSE events from LangGraph stream using high-level messages mode.
    
    Robust Parsing Strategy:
    1. Handle ToolMessage (outputs) -> Emit tool_output.
    2. Handle AIMessage structured tool_calls -> Emit tool_call.
    3. Prefer `reasoning_content` from kwargs if available (strip <think>).
    4. Fallback: Parse `msg.content` as a raw stream that may contain mixed thinking/content/tool_xml.
       - Use a State Machine (Content -> Thinking -> ToolSkipping -> Content).
       - Detect <think> to enter Thinking state.
       - Detect </think> to enter Content state.
       - Detect <tool_call> to enter ToolSkipping state (suppress raw XML).
    """
    
    # State
    buffer = ""
    is_thinking = False
    is_tool_skipping = False
    
    # Constants
    START_THINK = "<think>"
    END_THINK = "</think>"
    START_TOOL = "<tool_call>"
    END_TOOL = "</tool_call>"
    
    try:
        async for msg, metadata in graph.astream(inputs, config=config, stream_mode="messages"):
            # --- 1. Handle Tool Outputs (ToolMessage) ---
            if isinstance(msg, ToolMessage):
                yield f"data: {json.dumps({'type': 'tool_output', 'id': msg.tool_call_id, 'output': str(msg.content)})}\n\n"
                continue

            # --- 2. Handle Structured Tool Calls (AIMessage) ---
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                 for tool_call in msg.tool_calls:
                     # Emit structural tool call event
                     yield f"data: {json.dumps({'type': 'tool_call', 'tool': tool_call.get('name'), 'args': tool_call.get('args'), 'id': tool_call.get('id')})}\n\n"
                 
                 # Optimization: specific check to avoid leaking raw xml if structural parsing succeeded
                 continue

            if not hasattr(msg, 'content'):
                continue

            # --- 3. Handle Explicit Reasoning (kwargs from vLLM) ---
            reasoning_chunk = ""
            if hasattr(msg, 'additional_kwargs'):
                reasoning_chunk = msg.additional_kwargs.get('reasoning_content') or msg.additional_kwargs.get('reasoning') or ""
                
            if not reasoning_chunk and hasattr(msg, 'content_blocks') and msg.content_blocks:
                 for block in msg.content_blocks:
                    if isinstance(block, dict) and block.get("type") == "reasoning":
                        reasoning_chunk = block.get("reasoning", "")
                        break
            
            if reasoning_chunk:
                clean_reasoning = reasoning_chunk.replace("<think>", "").replace("</think>", "")
                if clean_reasoning:
                    yield f"data: {json.dumps({'type': 'thinking', 'content': clean_reasoning})}\n\n"

            # --- 4. Handle Content Stream ---
            text_chunk = ""
            if isinstance(msg.content, str):
                text_chunk = msg.content
            elif isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, str):
                         text_chunk += block
                    elif isinstance(block, dict) and "text" in block:
                         text_chunk += block["text"]
                    elif hasattr(block, "text"):
                         text_chunk += block.text
            
            if not text_chunk:
                continue
            
            buffer += text_chunk
            
            # State Machine Loop
            while True:
                if is_thinking:
                    # In Thinking State
                    end_idx = buffer.find(END_THINK)
                    if end_idx != -1:
                        if end_idx > 0:
                            yield f"data: {json.dumps({'type': 'thinking', 'content': buffer[:end_idx]})}\n\n"
                        is_thinking = False
                        buffer = buffer[end_idx + len(END_THINK):]
                    else:
                         partial_len = 0
                         for i in range(1, len(END_THINK)):
                            if i > len(buffer): break
                            if END_THINK.startswith(buffer[-i:]):
                                partial_len = i
                        
                         if partial_len > 0:
                             safe_len = len(buffer) - partial_len
                             if safe_len > 0:
                                 yield f"data: {json.dumps({'type': 'thinking', 'content': buffer[:safe_len]})}\n\n"
                             buffer = buffer[-partial_len:]
                             break
                         else:
                             if buffer:
                                 yield f"data: {json.dumps({'type': 'thinking', 'content': buffer})}\n\n"
                             buffer = ""
                             break

                elif is_tool_skipping:
                    # In Tool Skipping State - Suppress RAW XML
                    end_idx = buffer.find(END_TOOL)
                    if end_idx != -1:
                        # Found end of tool block. Resume content.
                        is_tool_skipping = False
                        buffer = buffer[end_idx + len(END_TOOL):]
                    else:
                        # Still inside tool block. Discard safe content (it's garbage raw xml).
                        partial_len = 0
                        for i in range(1, len(END_TOOL)):
                            if i > len(buffer): break
                            if END_TOOL.startswith(buffer[-i:]):
                                partial_len = i
                        
                        if partial_len > 0:
                            buffer = buffer[-partial_len:] # Keep potential end tag
                        else:
                            buffer = "" # Discard all raw XML
                        break

                else:
                    # Content State
                    next_think_idx = buffer.find(START_THINK)
                    next_tool_idx = buffer.find(START_TOOL)
                    
                    found_tag = None
                    idx = -1
                    
                    if next_think_idx != -1 and next_tool_idx != -1:
                        if next_think_idx < next_tool_idx:
                            found_tag = 'think'; idx = next_think_idx
                        else:
                            found_tag = 'tool'; idx = next_tool_idx
                    elif next_think_idx != -1:
                        found_tag = 'think'; idx = next_think_idx
                    elif next_tool_idx != -1:
                        found_tag = 'tool'; idx = next_tool_idx
                        
                    if found_tag:
                         # Emit content before tag
                        if idx > 0:
                            yield f"data: {json.dumps({'type': 'content', 'content': buffer[:idx]})}\n\n"
                        
                        if found_tag == 'think':
                            is_thinking = True
                            buffer = buffer[idx + len(START_THINK):]
                        else:
                            is_tool_skipping = True
                            buffer = buffer[idx + len(START_TOOL):]
                    else:
                         # No tags found, partial check
                         max_partial = 0
                         for tag in [START_THINK, START_TOOL]:
                             for i in range(1, len(tag)):
                                 if i > len(buffer): break
                                 if tag.startswith(buffer[-i:]):
                                     if i > max_partial: max_partial = i
                         
                         if max_partial > 0:
                             safe_len = len(buffer) - max_partial
                             if safe_len > 0:
                                 yield f"data: {json.dumps({'type': 'content', 'content': buffer[:safe_len]})}\n\n"
                             buffer = buffer[-max_partial:]
                             break
                         else:
                             if buffer:
                                 yield f"data: {json.dumps({'type': 'content', 'content': buffer})}\n\n"
                             buffer = ""
                             break

        if buffer:
            event_type = "thinking" if is_thinking else "content"
            clean = buffer.replace(START_THINK, "").replace(END_THINK, "")
            if clean:
                yield f"data: {json.dumps({'type': event_type, 'content': clean})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        # Padding to flush buffer
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
