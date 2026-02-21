"""Presentation layer - Session routes.

会话管理 API 端点。
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ...application.dto import (
    CreateSessionRequest,
    MessageResponse,
    SessionListResponse,
    SessionResponse,
)
from ...deps import get_chat_service

if TYPE_CHECKING:
    from ...application.services import ChatService

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_to_response(session) -> SessionResponse:
    """将 Session 实体转换为响应 DTO。"""
    return SessionResponse(
        id=session.id,
        title=session.title,
        messages=[
            MessageResponse(
                id=msg.id,
                role=msg.role.value,
                content=msg.content,
                thinking=msg.thinking,
                tool_calls=msg.tool_calls,
                chart_data=msg.chart_data,
                created_at=msg.created_at,
            )
            for msg in session.messages
        ],
        is_interrupted=session.is_interrupted,
        interrupt_data=session.interrupt_data,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateSessionRequest,
    chat_service: "ChatService" = Depends(get_chat_service),
) -> SessionResponse:
    """创建新会话。"""
    session = await chat_service.create_session(title=request.title)
    return _session_to_response(session)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    limit: int = 50,
    offset: int = 0,
    chat_service: "ChatService" = Depends(get_chat_service),
) -> SessionListResponse:
    """列出所有会话。"""
    sessions = await chat_service.list_sessions(limit=limit, offset=offset)
    return SessionListResponse(
        sessions=[_session_to_response(s) for s in sessions],
        total=len(sessions),  # TODO: 实际总数
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    chat_service: "ChatService" = Depends(get_chat_service),
) -> SessionResponse:
    """获取单个会话。"""
    session = await chat_service.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )
    return _session_to_response(session)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    chat_service: "ChatService" = Depends(get_chat_service),
) -> None:
    """删除会话。"""
    success = await chat_service.delete_session(session_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )
