"""PostgreSQL Store 和 Checkpointer 初始化模块

提供基于 PostgreSQL 的长期记忆存储和会话检查点。
使用同步版本的 PostgresSaver 以满足 create_deep_agent 的要求。
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Generator

from .config import get_settings

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore

_LOGGER = logging.getLogger(__name__)

# 全局单例 - 在模块加载时初始化
_checkpointer: "PostgresSaver | None" = None
_store: "PostgresStore | None" = None


def _init_postgres_checkpointer() -> "PostgresSaver":
    """初始化同步版本的 PostgresSaver"""
    from langgraph.checkpoint.postgres import PostgresSaver
    
    settings = get_settings()
    conn_string = settings.postgres_uri
    
    _LOGGER.info("Initializing PostgresSaver: %s", 
                 conn_string.replace(settings.postgres_password, "***"))
    
    # from_conn_string 是 context manager，但我们需要手动管理连接
    # 使用 __enter__ 来获取 saver 实例
    cm = PostgresSaver.from_conn_string(conn_string)
    saver = cm.__enter__()
    
    # 创建表
    saver.setup()
    _LOGGER.info("PostgresSaver initialized and tables created")
    
    return saver


def _init_postgres_store() -> "PostgresStore":
    """初始化同步版本的 PostgresStore"""
    from langgraph.store.postgres import PostgresStore
    
    settings = get_settings()
    conn_string = settings.postgres_uri
    
    _LOGGER.info("Initializing PostgresStore: %s",
                 conn_string.replace(settings.postgres_password, "***"))
    
    # PostgresStore 也是 context manager
    cm = PostgresStore.from_conn_string(conn_string)
    store = cm.__enter__()
    
    store.setup()
    _LOGGER.info("PostgresStore initialized and tables created")
    
    return store


def get_postgres_checkpointer() -> "PostgresSaver":
    """获取全局 PostgresSaver 单例
    
    用于会话检查点持久化（对话历史）。
    返回的是实例，不是函数，满足 create_deep_agent 的要求。
    """
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = _init_postgres_checkpointer()
    return _checkpointer


def get_postgres_store() -> "PostgresStore":
    """获取全局 PostgresStore 单例
    
    用于长期记忆存储（用户画像、历史摘要等）。
    """
    global _store
    if _store is None:
        _store = _init_postgres_store()
    return _store
