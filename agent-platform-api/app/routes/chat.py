import json
import logging
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..models.db_models import SessionModel, AgentModel
from ..core.agent_registry import registry
from langchain_core.messages import HumanMessage

router = APIRouter(prefix="/sessions", tags=["chat"])
_LOGGER = logging.getLogger(__name__)

async def event_generator(graph, message: str, config: dict) -> AsyncGenerator[str, None]:
    """Generate SSE events from LangGraph stream."""
    inputs = {"messages": [HumanMessage(content=message)]}
    
    try:
        async for event in graph.astream_events(inputs, config=config, version="v1"):
            kind = event["event"]
            
            # Dispatch events based on kind
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    # Send text chunk
                    yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
            
            elif kind == "on_tool_start":
                # Maybe notify tool usage
                pass
                
            # Handle other events or errors
            
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        
    except Exception as e:
        _LOGGER.error(f"Stream error: {e}")
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

    return StreamingResponse(
        event_generator(graph, message, config),
        media_type="text/event-stream"
    )
