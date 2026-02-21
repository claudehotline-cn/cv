"""Application layer - Chat Service implementation.

业务服务 - 编排仓库和 Agent 执行。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional
from uuid import UUID

from ..domain.entities import (
    EventType,
    FeedbackRequest,
    Message,
    MessageRole,
    Session,
    StreamEvent,
)

if TYPE_CHECKING:
    from ..domain.interfaces import IAgentRunner, ISessionRepository

_LOGGER = logging.getLogger(__name__)


class ChatService:
    """聊天服务 - 实现 IChatService 接口。
    
    遵循依赖倒置原则，通过构造函数注入依赖。
    """
    
    def __init__(
        self,
        session_repo: "ISessionRepository",
        agent_runner: "IAgentRunner",
    ) -> None:
        """
        Args:
            session_repo: 会话仓库
            agent_runner: Agent 执行器
        """
        self._session_repo = session_repo
        self._agent_runner = agent_runner
    
    async def create_session(self, title: str = "新对话") -> Session:
        """创建新会话。"""
        session = Session(title=title)
        await self._session_repo.create(session)
        _LOGGER.info(f"Created session: {session.id}")
        return session
    
    async def get_session(self, session_id: UUID) -> Optional[Session]:
        """获取会话。"""
        return await self._session_repo.get_by_id(session_id)
    
    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[Session]:
        """列出会话。"""
        return await self._session_repo.list_all(limit=limit, offset=offset)
    
    async def delete_session(self, session_id: UUID) -> bool:
        """删除会话。"""
        return await self._session_repo.delete(session_id)
    
    async def chat(
        self,
        session_id: UUID,
        message: str,
        config: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """发送消息并流式返回响应。
        
        1. 获取会话
        2. 添加用户消息
        3. 执行 Agent
        4. 保存 AI 响应
        """
        # 获取会话
        session = await self._session_repo.get_by_id(session_id)
        if session is None:
            yield StreamEvent(
                event=EventType.ERROR,
                data={"message": f"Session not found: {session_id}"},
            )
            return
        
        # 添加用户消息
        user_msg = Message(role=MessageRole.USER, content=message)
        session.messages.append(user_msg)
        await self._session_repo.update(session)
        
        # 收集 AI 响应内容
        ai_content = ""
        ai_thinking = ""
        chart_data = None
        is_interrupted = False
        interrupt_data = None
        
        # 执行 Agent 并流式返回
        async for event in self._agent_runner.stream(session, message, config):
            # 收集内容用于保存
            if event.event == EventType.CONTENT_DELTA:
                ai_content += event.data.get("delta", "")
            elif event.event == EventType.THINKING_DELTA:
                ai_thinking += event.data.get("delta", "")
            elif event.event == EventType.CHART:
                chart_data = event.data
            elif event.event == EventType.INTERRUPT:
                is_interrupted = True
                interrupt_data = event.data
            
            yield event
        
        # 保存 AI 响应消息
        if ai_content or ai_thinking:
            ai_msg = Message(
                role=MessageRole.ASSISTANT,
                content=ai_content,
                thinking=ai_thinking if ai_thinking else None,
                chart_data=chart_data,
            )
            session.messages.append(ai_msg)
        
        # 更新会话状态
        session.is_interrupted = is_interrupted
        session.interrupt_data = interrupt_data
        await self._session_repo.update(session)
    
    async def send_feedback(
        self,
        session_id: UUID,
        feedback: FeedbackRequest,
    ) -> AsyncIterator[StreamEvent]:
        """发送 HITL 反馈并恢复执行。"""
        # 获取会话
        session = await self._session_repo.get_by_id(session_id)
        if session is None:
            yield StreamEvent(
                event=EventType.ERROR,
                data={"message": f"Session not found: {session_id}"},
            )
            return
        
        if not session.is_interrupted:
            yield StreamEvent(
                event=EventType.ERROR,
                data={"message": "Session is not interrupted"},
            )
            return
        
        # 收集新响应
        ai_content = ""
        chart_data = None
        
        # 恢复执行
        async for event in self._agent_runner.resume(session, feedback):
            if event.event == EventType.CONTENT_DELTA:
                ai_content += event.data.get("delta", "")
            elif event.event == EventType.CHART:
                chart_data = event.data
            
            yield event
        
        # 保存新响应
        if ai_content:
            ai_msg = Message(
                role=MessageRole.ASSISTANT,
                content=ai_content,
                chart_data=chart_data,
            )
            session.messages.append(ai_msg)
        
        # 清除中断状态
        session.is_interrupted = False
        session.interrupt_data = None
        await self._session_repo.update(session)
    
    async def get_state(self, session_id: UUID) -> Optional[dict[str, Any]]:
        """获取会话状态。"""
        session = await self._session_repo.get_by_id(session_id)
        if session:
            return {
                "is_interrupted": session.is_interrupted,
                "interrupt_data": session.interrupt_data,
                "message_count": len(session.messages),
            }
        return None
