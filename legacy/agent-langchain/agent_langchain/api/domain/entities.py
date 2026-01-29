"""Domain entities for Agent Chat API.

实体定义 - 核心业务对象，不依赖任何外部框架。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4


class MessageRole(str, Enum):
    """消息角色枚举。"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class EventType(str, Enum):
    """SSE 事件类型枚举。"""
    # 生命周期
    MESSAGE_START = "message_start"
    MESSAGE_END = "message_end"
    ERROR = "error"
    
    # 内容
    CONTENT_DELTA = "content_delta"
    
    # 思维链
    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"
    THINKING_END = "thinking_end"
    
    # 工具调用
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    
    # 图表
    CHART = "chart"
    
    # HITL
    INTERRUPT = "interrupt"
    FEEDBACK_RECEIVED = "feedback_received"


@dataclass
class Message:
    """聊天消息实体。"""
    id: UUID = field(default_factory=uuid4)
    role: MessageRole = MessageRole.USER
    content: str = ""
    thinking: Optional[str] = None  # 思维链内容
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    chart_data: Optional[dict[str, Any]] = None  # ECharts 配置
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    """会话实体。"""
    id: UUID = field(default_factory=uuid4)
    title: str = "新对话"
    messages: list[Message] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)  # Agent 状态
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # HITL 相关
    is_interrupted: bool = False
    interrupt_data: Optional[dict[str, Any]] = None


@dataclass
class StreamEvent:
    """SSE 流事件。"""
    event: EventType
    data: dict[str, Any]
    id: Optional[str] = None
    
    def to_sse(self) -> str:
        """转换为 SSE 格式字符串。"""
        import json
        lines = []
        if self.id:
            lines.append(f"id: {self.id}")
        lines.append(f"event: {self.event.value}")
        lines.append(f"data: {json.dumps(self.data, ensure_ascii=False)}")
        lines.append("")  # 空行分隔
        return "\n".join(lines) + "\n"


@dataclass
class FeedbackRequest:
    """HITL 反馈请求。"""
    decision: str  # "approve" | "reject"
    message: Optional[str] = None
