"""Application layer - Data Transfer Objects (DTOs)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# =============================================================================
# Request DTOs
# =============================================================================

class CreateSessionRequest(BaseModel):
    """创建会话请求。"""
    title: str = Field(default="新对话", description="会话标题")


class ChatRequest(BaseModel):
    """发送消息请求。"""
    message: str = Field(..., description="用户消息内容")
    config: Optional[dict[str, Any]] = Field(default=None, description="运行时配置")


class FeedbackRequest(BaseModel):
    """HITL 反馈请求。"""
    decision: str = Field(..., description="决策: approve 或 reject")
    message: Optional[str] = Field(default=None, description="反馈消息")


# =============================================================================
# Response DTOs
# =============================================================================

class MessageResponse(BaseModel):
    """消息响应。"""
    id: UUID
    role: str
    content: str
    thinking: Optional[str] = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    chart_data: Optional[dict[str, Any]] = None
    created_at: datetime


class SessionResponse(BaseModel):
    """会话响应。"""
    id: UUID
    title: str
    messages: list[MessageResponse] = Field(default_factory=list)
    is_interrupted: bool = False
    interrupt_data: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    """会话列表响应。"""
    sessions: list[SessionResponse]
    total: int


class StateResponse(BaseModel):
    """状态响应。"""
    is_interrupted: bool
    interrupt_data: Optional[dict[str, Any]] = None
    message_count: int
