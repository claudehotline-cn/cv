"""Article Deep Agent (Multi-Agent Version)：基于 deepagents 实现的分层多智能体文章生成系统。"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StoreBackend

# 使用 agent-core 统一基础设施
from agent_core.runtime import build_chat_llm
from agent_core.store import get_async_store, get_checkpointer
from agent_core.middleware import SubAgentHITLMiddleware, FileAttachmentMiddleware
from .middleware import TaskContextMiddleware

from .prompts import MAIN_AGENT_PROMPT
from .schemas import ArticleAgentOutput

# Import Refactored Sub-Agents
from .subagents.ingest import ingest_agent
from .subagents.planner import planner_agent
from .subagents.researcher import researcher_agent
from .subagents.writer import writer_agent
from .subagents.reviewer import reviewer_agent
from .subagents.assembler import assembler_agent

_LOGGER = logging.getLogger("article_agent.article_deep_graph")


def get_article_deep_agent_graph() -> Any:
    """构造并返回 Article Deep Agent (Multi-Agent 架构)。"""
    
    # 使用 agent-core 统一 LLM 配置 (Main Agent)
    main_llm = build_chat_llm(task_name="article_deep_main")
    
    # ============================================================================
    # 创建主 Deep Agent
    # ============================================================================
    
    try:
        from langchain.agents.structured_output import ToolStrategy
        response_format = ToolStrategy(ArticleAgentOutput)
    except ImportError:
        response_format = ArticleAgentOutput
    
    # 创建 Deep Agent (使用 agent-core 基础设施)
    graph = create_deep_agent(
        model=main_llm,
        subagents=[
            ingest_agent,
            planner_agent,
            researcher_agent,
            writer_agent,
            reviewer_agent,
            assembler_agent,
        ],
        tools=[],
        system_prompt=MAIN_AGENT_PROMPT,
        middleware=[
            # 上下文同步
            TaskContextMiddleware(),
            # 文件上传处理
            FileAttachmentMiddleware(),
            # HITL: 在 assembler 输出时触发审核
            SubAgentHITLMiddleware(
                interrupt_subagents=["assembler_agent"],
                allowed_decisions=["approve", "reject"],
                description={
                    "assembler_agent": "文章生成完成，请确认是否发布",
                    "default": "操作完成，请确认是否继续"
                },
            ),
        ],
        backend=lambda rt: CompositeBackend(
            default=FilesystemBackend(
                root_dir=f"/data/workspace/{rt.config.get('configurable', {}).get('session_id', 'default')}/{rt.config.get('configurable', {}).get('task_id', 'main')}",
                virtual_mode=True
            ),
            routes={
                "/_shared/": StoreBackend(rt),
            }
        ),
        store=get_async_store,
        checkpointer=get_checkpointer(),
        response_format=response_format,
    )
    
    _LOGGER.info("Article Deep Agent graph created with 6 SubAgents")
    
    return graph


__all__ = ["get_article_deep_agent_graph"]
