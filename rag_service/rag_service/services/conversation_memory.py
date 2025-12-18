"""对话历史记忆服务 - 支持多轮对话上下文"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import time

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """单条聊天消息"""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: float = field(default_factory=time.time)


class ConversationMemory:
    """对话历史管理器 (内存存储)"""
    
    def __init__(self, max_messages: int = 10, max_sessions: int = 1000):
        """
        Args:
            max_messages: 每个会话保留的最大消息数
            max_sessions: 最大会话数 (超过后清理最旧的)
        """
        self.max_messages = max_messages
        self.max_sessions = max_sessions
        self.sessions: Dict[str, List[ChatMessage]] = defaultdict(list)
        self.last_access: Dict[str, float] = {}
    
    def add_message(self, session_id: str, role: str, content: str):
        """添加消息到会话"""
        if not session_id:
            return
        
        # 更新访问时间
        self.last_access[session_id] = time.time()
        
        # 添加消息
        self.sessions[session_id].append(ChatMessage(
            role=role,
            content=content,
        ))
        
        # 保持消息数量限制
        if len(self.sessions[session_id]) > self.max_messages:
            self.sessions[session_id] = self.sessions[session_id][-self.max_messages:]
        
        # 清理旧会话
        self._cleanup_old_sessions()
    
    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """获取会话历史 (格式化为LLM可用的格式)"""
        if not session_id or session_id not in self.sessions:
            return []
        
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.sessions[session_id]
        ]
    
    def get_history_text(self, session_id: str) -> str:
        """获取会话历史 (纯文本格式)"""
        history = self.get_history(session_id)
        if not history:
            return ""
        
        lines = []
        for msg in history:
            role_cn = "用户" if msg["role"] == "user" else "助手"
            lines.append(f"{role_cn}: {msg['content']}")
        
        return "\n".join(lines)
    
    def clear_session(self, session_id: str):
        """清除指定会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self.last_access:
            del self.last_access[session_id]
    
    def _cleanup_old_sessions(self):
        """清理最旧的会话 (当超过最大会话数时)"""
        if len(self.sessions) <= self.max_sessions:
            return
        
        # 按最后访问时间排序
        sorted_sessions = sorted(
            self.last_access.items(),
            key=lambda x: x[1]
        )
        
        # 删除最旧的会话
        sessions_to_remove = len(self.sessions) - self.max_sessions
        for session_id, _ in sorted_sessions[:sessions_to_remove]:
            self.clear_session(session_id)
        
        logger.info(f"Cleaned up {sessions_to_remove} old sessions")


# 单例
conversation_memory = ConversationMemory()
