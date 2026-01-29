"""Presentation layer - Chat routes.

聊天和 HITL 反馈 API 端点。
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from ...application.dto import ChatRequest, FeedbackRequest, StateResponse
from ...deps import get_chat_service
from ...domain.entities import FeedbackRequest as DomainFeedbackRequest

if TYPE_CHECKING:
    from ...application.services import ChatService

router = APIRouter(prefix="/sessions", tags=["chat"])


@router.post("/{session_id}/stream")
async def stream_chat(
    session_id: UUID,
    request: ChatRequest,
    chat_service: "ChatService" = Depends(get_chat_service),
) -> StreamingResponse:
    """流式对话 - 发送消息并通过 SSE 返回响应。"""
    
    async def event_generator():
        async for event in chat_service.chat(
            session_id=session_id,
            message=request.message,
            config=request.config,
        ):
            yield event.to_sse()
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("/{session_id}/feedback")
async def send_feedback(
    session_id: UUID,
    request: FeedbackRequest,
    chat_service: "ChatService" = Depends(get_chat_service),
) -> StreamingResponse:
    """发送 HITL 反馈并流式返回后续响应。"""
    
    # 转换为领域对象
    feedback = DomainFeedbackRequest(
        decision=request.decision,
        message=request.message,
    )
    
    async def event_generator():
        async for event in chat_service.send_feedback(
            session_id=session_id,
            feedback=feedback,
        ):
            yield event.to_sse()
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{session_id}/state", response_model=StateResponse)
async def get_state(
    session_id: UUID,
    chat_service: "ChatService" = Depends(get_chat_service),
) -> StateResponse:
    """获取会话状态（用于检查是否有待处理的 HITL 中断）。"""
    state = await chat_service.get_state(session_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )
    return StateResponse(**state)
