"""Infrastructure - Session Repository implementations.

数据持久化实现 - 使用 PostgreSQL 存储会话数据。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from ..domain.entities import Message, MessageRole, Session

_LOGGER = logging.getLogger(__name__)


class InMemorySessionRepository:
    """内存会话仓库 - 用于开发和测试。
    
    实现 ISessionRepository 接口（鸭子类型）。
    """
    
    def __init__(self) -> None:
        self._sessions: dict[UUID, Session] = {}
    
    async def get_by_id(self, session_id: UUID) -> Optional[Session]:
        """根据 ID 获取会话。"""
        return self._sessions.get(session_id)
    
    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Session]:
        """列出所有会话，按更新时间倒序。"""
        sessions = sorted(
            self._sessions.values(),
            key=lambda s: s.updated_at,
            reverse=True,
        )
        return sessions[offset : offset + limit]
    
    async def create(self, session: Session) -> Session:
        """创建新会话。"""
        self._sessions[session.id] = session
        _LOGGER.info(f"Created session: {session.id}")
        return session
    
    async def update(self, session: Session) -> Session:
        """更新会话。"""
        session.updated_at = datetime.now()
        self._sessions[session.id] = session
        return session
    
    async def delete(self, session_id: UUID) -> bool:
        """删除会话。"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False


class PostgresSessionRepository:
    """PostgreSQL 会话仓库 - 生产环境使用。
    
    复用现有的 PostgreSQL 基础设施。
    """
    
    def __init__(self, connection_string: str) -> None:
        self._conn_str = connection_string
        # 使用 asyncpg 或 SQLAlchemy async
        self._pool = None
    
    async def _ensure_pool(self) -> None:
        """确保连接池已初始化。"""
        if self._pool is None:
            import asyncpg
            self._pool = await asyncpg.create_pool(self._conn_str)
            # 创建表（如果不存在）
            await self._create_tables()
    
    async def _create_tables(self) -> None:
        """创建必要的表。"""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id UUID PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '新对话',
                    messages JSONB NOT NULL DEFAULT '[]',
                    state JSONB NOT NULL DEFAULT '{}',
                    is_interrupted BOOLEAN NOT NULL DEFAULT FALSE,
                    interrupt_data JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
    
    async def get_by_id(self, session_id: UUID) -> Optional[Session]:
        """根据 ID 获取会话。"""
        await self._ensure_pool()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM chat_sessions WHERE id = $1",
                session_id,
            )
            if row:
                return self._row_to_session(row)
        return None
    
    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Session]:
        """列出所有会话。"""
        await self._ensure_pool()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM chat_sessions 
                ORDER BY updated_at DESC 
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
            return [self._row_to_session(row) for row in rows]
    
    async def create(self, session: Session) -> Session:
        """创建新会话。"""
        await self._ensure_pool()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO chat_sessions (id, title, messages, state, is_interrupted, interrupt_data, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                session.id,
                session.title,
                json.dumps([self._message_to_dict(m) for m in session.messages]),
                json.dumps(session.state),
                session.is_interrupted,
                json.dumps(session.interrupt_data) if session.interrupt_data else None,
                session.created_at,
                session.updated_at,
            )
        return session
    
    async def update(self, session: Session) -> Session:
        """更新会话。"""
        await self._ensure_pool()
        session.updated_at = datetime.now()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE chat_sessions 
                SET title = $2, messages = $3, state = $4, 
                    is_interrupted = $5, interrupt_data = $6, updated_at = $7
                WHERE id = $1
                """,
                session.id,
                session.title,
                json.dumps([self._message_to_dict(m) for m in session.messages]),
                json.dumps(session.state),
                session.is_interrupted,
                json.dumps(session.interrupt_data) if session.interrupt_data else None,
                session.updated_at,
            )
        return session
    
    async def delete(self, session_id: UUID) -> bool:
        """删除会话。"""
        await self._ensure_pool()
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM chat_sessions WHERE id = $1",
                session_id,
            )
            return "DELETE 1" in result
    
    def _row_to_session(self, row: Any) -> Session:
        """将数据库行转换为 Session 实体。"""
        messages_data = json.loads(row["messages"]) if isinstance(row["messages"], str) else row["messages"]
        messages = [self._dict_to_message(m) for m in messages_data]
        
        return Session(
            id=row["id"],
            title=row["title"],
            messages=messages,
            state=json.loads(row["state"]) if isinstance(row["state"], str) else row["state"],
            is_interrupted=row["is_interrupted"],
            interrupt_data=json.loads(row["interrupt_data"]) if row["interrupt_data"] else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    
    def _message_to_dict(self, msg: Message) -> dict:
        """将 Message 实体转换为字典。"""
        return {
            "id": str(msg.id),
            "role": msg.role.value,
            "content": msg.content,
            "thinking": msg.thinking,
            "tool_calls": msg.tool_calls,
            "chart_data": msg.chart_data,
            "created_at": msg.created_at.isoformat(),
            "metadata": msg.metadata,
        }
    
    def _dict_to_message(self, data: dict) -> Message:
        """将字典转换为 Message 实体。"""
        from uuid import UUID as UUIDType
        return Message(
            id=UUIDType(data["id"]),
            role=MessageRole(data["role"]),
            content=data["content"],
            thinking=data.get("thinking"),
            tool_calls=data.get("tool_calls", []),
            chart_data=data.get("chart_data"),
            created_at=datetime.fromisoformat(data["created_at"]),
            metadata=data.get("metadata", {}),
        )
