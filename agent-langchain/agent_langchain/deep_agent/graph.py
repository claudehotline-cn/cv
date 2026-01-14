"""统一数据分析 Deep Agent (Multi-Agent Version)：基于 deepagents 实现的分层多智能体系统。"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StoreBackend
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from ..llm_runtime import build_chat_llm
from ..middleware import ThinkingLoggerMiddleware, FileContentInjectionMiddleware, SubAgentHITLMiddleware
from .prompts import MAIN_AGENT_PROMPT

# Import Refactored Sub-Agents
from .subagents.sql import sql_agent
from .subagents.excel import excel_agent
from .subagents.python import python_agent
from .subagents.visualizer import visualizer_agent
from .subagents.reviewer import reviewer_agent
from .subagents.report import report_agent

_LOGGER = logging.getLogger("agent_langchain.data_deep_graph")

def get_data_deep_agent_graph() -> Any:
    """构造并返回统一的数据分析 Deep Agent (Multi-Agent 架构)。"""
    
    # 统一使用 qwen3:30b 模型 (Main Agent)
    main_llm = build_chat_llm(task_name="data_deep_main")
    
    # ============================================================================
    # 创建主 Deep Agent
    # ============================================================================
    from ..schemas import MainAgentOutput
    try:
        from langchain.agents.structured_output import ToolStrategy
        response_format = ToolStrategy(MainAgentOutput)
    except ImportError:
        response_format = MainAgentOutput

    graph = create_deep_agent(
        model=main_llm,
        subagents=[
            sql_agent, excel_agent, python_agent, reviewer_agent,
            visualizer_agent, report_agent
        ],
        tools=[],
        system_prompt=MAIN_AGENT_PROMPT,
        middleware=[
            ThinkingLoggerMiddleware(),
            SubAgentHITLMiddleware(
                interrupt_subagents=["visualizer_agent"],
                allowed_decisions=["approve", "reject"],
                description="图表生成完成，请确认是否继续生成报告",
            ),
            FileContentInjectionMiddleware(),
        ],
        backend=lambda rt: CompositeBackend(
            default=FilesystemBackend(root_dir="/data/workspace", virtual_mode=True),
            routes={"/_shared/": StoreBackend(rt)},
        ),
        store=lambda: InMemoryStore(),  # Use factory for fresh store per instance/run
        checkpointer=InMemorySaver(),   # Required for HITL
        response_format=response_format,
    )
    
    return graph

