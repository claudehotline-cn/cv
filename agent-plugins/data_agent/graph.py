"""统一数据分析 Deep Agent (Multi-Agent Version)：基于 deepagents 实现的分层多智能体系统。"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StoreBackend

from agent_core.runtime import build_chat_llm
from agent_core.middleware import SensitiveToolMiddleware, FixedTodoListMiddleware
import deepagents.graph
# Explicitly patch locally to ensure it takes effect before create_deep_agent uses it
deepagents.graph.TodoListMiddleware = FixedTodoListMiddleware
from agent_core.store import get_async_store, get_checkpointer
from .prompts import MAIN_AGENT_PROMPT

# Import Refactored Sub-Agents
from .subagents.sql import sql_agent
from .subagents.excel import excel_agent
from .subagents.python import python_agent
from .subagents.visualizer import visualizer_agent
from .subagents.reviewer import reviewer_agent
from .subagents.report import report_agent
from agent_core.events import RedisEventBus, AuditEmitter
from agent_core.settings import get_settings

_settings = get_settings()

# Lazy init to track event loop correctly
_redis_bus = None
_audit_emitter = None

def _get_audit_emitter():
    global _redis_bus, _audit_emitter
    if _audit_emitter is None:
        _redis_bus = RedisEventBus(_settings.redis_url)
        _audit_emitter = AuditEmitter(_redis_bus.redis)
    return _audit_emitter

_LOGGER = logging.getLogger("agent_langchain.data_deep_graph")


def _get_graph_root_dir(rt) -> str:
    """Helper to calculate root directory using WorkspaceBackend."""
    from .config import get_backend
    
    # User feedback: rt has context, not config
    # deepagents Runtime.context typically holds the configurable parameters
    ctx = getattr(rt, "context", {}) or {}
    
    user_id = ctx.get("user_id", "anonymous")
    session_id = ctx.get("session_id", "default")
    task_id = ctx.get("task_id") or None
    
    # Workspace layout:
    # - Sync artifacts:  {session_id}/artifacts/
    # - Async artifacts: {session_id}/{task_id}/artifacts/
    backend = get_backend(user_id=user_id, session_id=session_id, task_id=task_id)
    return backend.artifacts_dir

def get_data_deep_agent_graph(
    checkpointer: Any = None,
    llm: Any = None
) -> Any:
    """构造并返回统一的数据分析 Deep Agent (Multi-Agent 架构)。"""
    
    # 统一使用 qwen3:30b 模型 (Main Agent)
    # 支持注入 Mock LLM
    main_llm = llm if llm is not None else build_chat_llm(task_name="data_deep_main")
    
    # ============================================================================
    # 创建主 Deep Agent
    # ============================================================================
    from .schemas import MainAgentOutput
    response_format = None

    # 支持注入 Mock Checkpointer
    cp = checkpointer if checkpointer is not None else get_checkpointer()

    graph = create_deep_agent(
        model=main_llm,
        subagents=[
            sql_agent, excel_agent, python_agent, reviewer_agent,
            visualizer_agent, report_agent
        ],
        tools=[],
        system_prompt=MAIN_AGENT_PROMPT,
        middleware=[
            SensitiveToolMiddleware(
                emitter=_get_audit_emitter(),
                sensitive_tools=["visualizer_agent", "report_agent"],
                allowed_decisions=["approve", "reject"],
                description={
                    "visualizer_agent": "图表生成完成，请确认是否继续",
                    "report_agent": "报告生成完成，请确认是否继续",
                    "default": "操作完成，请确认是否继续"
                },
            ),
            # FileContentInjectionMiddleware 已移除，改用 subgraph streaming 直接传输数据
        ],
        backend=lambda rt: CompositeBackend(
            default=FilesystemBackend(
                root_dir=_get_graph_root_dir(rt), 
                virtual_mode=True
            ),
            routes={"/_shared/": StoreBackend(rt)},
        ),
        # 使用 PostgreSQL 持久化存储（长期记忆 + 会话检查点）
        store=get_async_store,
        checkpointer=cp,  # 使用注入的或预初始化的实例
        response_format=response_format,
    )
    
    return graph
