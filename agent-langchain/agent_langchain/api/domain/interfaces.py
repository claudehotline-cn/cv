"""Domain interfaces (Protocols) for Agent Chat API.

接口定义 - 遵循 SOLID 原则的依赖倒置。
使用 Protocol 定义接口，允许结构化子类型（鸭子类型）。
"""
from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Optional, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from .entities import FeedbackRequest, Message, Session, StreamEvent


# =============================================================================
# Repository Interfaces (数据持久化)
# =============================================================================

class ISessionReader(Protocol):
    """会话读取接口 - 接口隔离原则 (I)。"""
    
    async def get_by_id(self, session_id: UUID) -> Optional["Session"]:
        """根据 ID 获取会话。"""
        ...
    
    async def list_all(self, limit: int = 50, offset: int = 0) -> list["Session"]:
        """列出所有会话。"""
        ...


class ISessionWriter(Protocol):
    """会话写入接口 - 接口隔离原则 (I)。"""
    
    async def create(self, session: "Session") -> "Session":
        """创建新会话。"""
        ...
    
    async def update(self, session: "Session") -> "Session":
        """更新会话。"""
        ...
    
    async def delete(self, session_id: UUID) -> bool:
        """删除会话。"""
        ...


class ISessionRepository(ISessionReader, ISessionWriter, Protocol):
    """完整会话仓库接口 - 组合读写接口。"""
    pass


# =============================================================================
# Event Emitter Interfaces (事件发送)
# =============================================================================

class IEventEmitter(Protocol):
    """事件发送器接口 - 开放封闭原则 (O)。
    
    可扩展为 SSE、WebSocket 等不同实现。
    """
    
    async def emit(self, event: "StreamEvent") -> None:
        """发送单个事件。"""
        ...
    
    async def close(self) -> None:
        """关闭发送器。"""
        ...


# =============================================================================
# Agent Interfaces (Agent 执行)
# =============================================================================

class IAgentRunner(Protocol):
    """Agent 执行器接口 - 单一职责原则 (S)。"""
    
    async def stream(
        self,
        session: "Session",
        user_message: str,
        config: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator["StreamEvent"]:
        """流式执行 Agent 并产生事件。"""
        ...
    
    async def resume(
        self,
        session: "Session",
        feedback: "FeedbackRequest",
    ) -> AsyncIterator["StreamEvent"]:
        """从 HITL 中断处恢复执行。"""
        ...


# =============================================================================
# Service Interfaces (业务服务)
# =============================================================================

class IChatService(Protocol):
    """聊天服务接口 - 编排业务流程。"""
    
    async def create_session(self) -> "Session":
        """创建新会话。"""
        ...
    
    async def get_session(self, session_id: UUID) -> Optional["Session"]:
        """获取会话。"""
        ...
    
    async def list_sessions(self, limit: int = 50) -> list["Session"]:
        """列出会话。"""
        ...
    
    async def chat(
        self,
        session_id: UUID,
        message: str,
    ) -> AsyncIterator["StreamEvent"]:
        """发送消息并流式返回响应。"""
        ...
    
    async def send_feedback(
        self,
        session_id: UUID,
        feedback: "FeedbackRequest",
    ) -> AsyncIterator["StreamEvent"]:
        """发送 HITL 反馈。"""
        ...
