"""Article Deep Agent (Multi-Agent Version)：基于 deepagents 实现的分层多智能体文章生成系统。"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StoreBackend

# 使用 agent-core 统一基础设施
from agent_core.runtime import build_chat_llm
from agent_core.store import get_async_store, get_checkpointer
from agent_core.middleware import SensitiveToolMiddleware, FileAttachmentMiddleware

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


def get_article_deep_agent_graph(model: Any = None, checkpointer: Any = None) -> Any:
    """构造并返回 Article Deep Agent (Multi-Agent 架构)。
    
    Args:
        model: Optional LLM instance. If None, builds default using build_chat_llm.
        checkpointer: Optional Checkpointer instance. If None, uses default global checkpointer.
    """
    
    # 使用 agent-core 统一 LLM 配置 (Main Agent)
    if model is None:
        main_llm = build_chat_llm(task_name="article_deep_main")
    else:
        main_llm = model
        
    # Checkpointer
    if checkpointer is None:
        cp = get_checkpointer()
    else:
        cp = checkpointer
    
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
            # 文件上传处理
            FileAttachmentMiddleware(),
            # HITL: 在 assembler 输出时触发审核 (Backward Compatibility)
            SensitiveToolMiddleware(
                sensitive_tools=["assembler_agent"],
                allowed_decisions=["approve", "reject"],
                description={
                    "assembler_agent": "文章生成完成，请确认是否发布",
                    "default": "操作完成，请确认是否继续"
                },
            ),
        ],
        backend=_create_backend_factory,
        store=get_async_store,
        checkpointer=cp,
        response_format=response_format,
    )
    
    _LOGGER.info("Article Deep Agent graph created with 6 SubAgents")
    return graph

def _create_backend_factory(rt):
    # Try to extract configuration from Runtime
    config = {}
    
    # helper to check known attributes
    if hasattr(rt, "config"):
        config = rt.config
    elif hasattr(rt, "context") and hasattr(rt.context, "config"):
        config = rt.context.config
    
    configurable = config.get("configurable", {})
    
    session_id = configurable.get("session_id", "default")
    task_id = configurable.get("task_id", "main")
    
    # If still default, try to inspect if it's a ToolRuntime with different structure
    if session_id == "default" and hasattr(rt, "metadata"):
         meta_session = rt.metadata.get("session_id")
         if meta_session:
             session_id = meta_session
             task_id = rt.metadata.get("task_id", "main")
    
    root_path = f"/data/workspace/{session_id}/{task_id}"

    return CompositeBackend(
            default=FilesystemBackend(
                root_dir=root_path,
                virtual_mode=True
            ),
            routes={
                "/_shared/": StoreBackend(rt),
            }
        )


__all__ = ["get_article_deep_agent_graph"]
