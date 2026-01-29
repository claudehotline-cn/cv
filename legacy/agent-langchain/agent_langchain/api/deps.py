"""Dependency Injection container.

依赖注入 - 遵循依赖倒置原则 (D)。
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application.services import ChatService
    from .domain.interfaces import IAgentRunner, ISessionRepository


@lru_cache()
def get_settings():
    """获取应用配置（单例）。"""
    return {
        "database_url": os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@pgvector:5432/langgraph"
        ),
        "use_memory_storage": os.getenv("USE_MEMORY_STORAGE", "true").lower() == "true",
    }


# =============================================================================
# Repository Factory
# =============================================================================

_session_repo_instance = None


def get_session_repository() -> "ISessionRepository":
    """获取会话仓库实例（单例）。"""
    global _session_repo_instance
    
    if _session_repo_instance is None:
        settings = get_settings()
        
        if settings["use_memory_storage"]:
            from .infrastructure.repositories import InMemorySessionRepository
            _session_repo_instance = InMemorySessionRepository()
        else:
            from .infrastructure.repositories import PostgresSessionRepository
            _session_repo_instance = PostgresSessionRepository(
                connection_string=settings["database_url"]
            )
    
    return _session_repo_instance


# =============================================================================
# Agent Factory
# =============================================================================

_agent_runner_instance = None


def get_agent_runner() -> "IAgentRunner":
    """获取 Agent 执行器实例（单例）。"""
    global _agent_runner_instance
    
    if _agent_runner_instance is None:
        from .infrastructure.agent_adapter import LangGraphAgentAdapter
        from ..deep_agent.graph import get_data_deep_agent_graph
        
        _agent_runner_instance = LangGraphAgentAdapter(
            graph_factory=get_data_deep_agent_graph
        )
    
    return _agent_runner_instance


# =============================================================================
# Service Factory
# =============================================================================

_chat_service_instance = None


def get_chat_service() -> "ChatService":
    """获取聊天服务实例（单例）。
    
    FastAPI Depends 使用此函数注入依赖。
    """
    global _chat_service_instance
    
    if _chat_service_instance is None:
        from .application.services import ChatService
        
        _chat_service_instance = ChatService(
            session_repo=get_session_repository(),
            agent_runner=get_agent_runner(),
        )
    
    return _chat_service_instance


# =============================================================================
# Reset (用于测试)
# =============================================================================

def reset_dependencies() -> None:
    """重置所有单例实例（用于测试）。"""
    global _session_repo_instance, _agent_runner_instance, _chat_service_instance
    _session_repo_instance = None
    _agent_runner_instance = None
    _chat_service_instance = None
    get_settings.cache_clear()
