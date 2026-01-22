"""Article Deep Agent (Multi-Agent Version)：基于 deepagents 实现的分层多智能体文章生成系统。"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent, SubAgent, CompiledSubAgent
from deepagents.backends import CompositeBackend, FilesystemBackend, StoreBackend
from langchain.agents import create_agent
from langchain_core.runnables import RunnableLambda

# 使用 agent-core 统一基础设施
from agent_core.runtime import build_chat_llm
from agent_core.store import get_async_store, get_checkpointer
from agent_core.middleware import SubAgentHITLMiddleware, FileAttachmentMiddleware
from .middleware import TaskContextMiddleware

from .prompts import (
    MAIN_AGENT_PROMPT,
    PLANNER_AGENT_PROMPT,
    PLANNER_AGENT_DESCRIPTION,
    RESEARCHER_AGENT_PROMPT,
    RESEARCHER_AGENT_DESCRIPTION,
    WRITER_AGENT_PROMPT,
    WRITER_AGENT_DESCRIPTION,
    REVIEWER_AGENT_PROMPT,
    REVIEWER_AGENT_DESCRIPTION,
    INGEST_AGENT_PROMPT,
    INGEST_AGENT_DESCRIPTION,
)
from .schemas import ArticleAgentOutput, AssemblerOutput, IngestOutput

# Import Refactored Sub-Agents
from .subagents.assembler import assembler_agent

from .tools import (
    load_file_tool,
    ingest_documents_tool,
    generate_outline_tool,
    read_sources_tool,
    research_section_tool,
    research_all_sections_tool,
    research_audit_tool,
    write_section_tool,
    write_all_sections_tool,
    writer_audit_tool,
    review_draft_tool,
    assemble_article_tool,
)

_LOGGER = logging.getLogger("article_agent.article_deep_graph")


def get_article_deep_agent_graph() -> Any:
    """构造并返回 Article Deep Agent (Multi-Agent 架构)。"""
    
    # 使用 agent-core 统一 LLM 配置
    main_llm = build_chat_llm(task_name="article_deep_main")
    
    # ============================================================================
    # 定义子 Agent (Sub-Agents)
    # ============================================================================
    
    # 0. Ingest Agent - 素材采集
    ingest_llm = build_chat_llm(task_name="ingest")
    ingest_tools = [ingest_documents_tool]
    ingest_llm_forced = ingest_llm.bind_tools(ingest_tools, tool_choice="required")
    ingest_runnable = create_agent(
        model=ingest_llm_forced,
        tools=ingest_tools,
        system_prompt=INGEST_AGENT_PROMPT,
        response_format=IngestOutput,
    )
    ingest_agent = CompiledSubAgent(
        name="ingest_agent",
        description=INGEST_AGENT_DESCRIPTION,
        runnable=ingest_runnable,
    )

    # 1. Planner Agent - 大纲规划
    planner_llm = build_chat_llm(task_name="planner")
    planner_tools = [generate_outline_tool]
    planner_llm_forced = planner_llm.bind_tools(
        planner_tools,
        tool_choice={"type": "function", "function": {"name": "generate_outline_tool"}}
    )
    planner_runnable = create_agent(
        model=planner_llm_forced,
        tools=planner_tools,
        system_prompt=PLANNER_AGENT_PROMPT,
    )
    planner_agent = CompiledSubAgent(
        name="planner_agent",
        description=PLANNER_AGENT_DESCRIPTION,
        runnable=planner_runnable,
    )
    
    # 2. Researcher Agent - 资料整理
    researcher_llm = build_chat_llm(task_name="researcher")
    researcher_tools = [research_all_sections_tool]
    researcher_llm_forced = researcher_llm.bind_tools(
        researcher_tools,
        tool_choice={"type": "function", "function": {"name": "research_all_sections_tool"}}
    )
    researcher_runnable = create_agent(
        model=researcher_llm_forced,
        tools=researcher_tools,
        system_prompt=RESEARCHER_AGENT_PROMPT,
    )
    researcher_agent = CompiledSubAgent(
        name="researcher_agent",
        description=RESEARCHER_AGENT_DESCRIPTION,
        runnable=researcher_runnable,
    )
    
    # 3. Writer Agent - 内容撰写
    writer_llm = build_chat_llm(task_name="writer")
    writer_tools = [write_all_sections_tool]
    writer_llm_forced = writer_llm.bind_tools(
        writer_tools,
        tool_choice={"type": "function", "function": {"name": "write_all_sections_tool"}}
    )
    writer_runnable = create_agent(
        model=writer_llm_forced,
        tools=writer_tools,
        system_prompt=WRITER_AGENT_PROMPT,
    )
    writer_agent = CompiledSubAgent(
        name="writer_agent",
        description=WRITER_AGENT_DESCRIPTION,
        runnable=writer_runnable,
    )
    
    # 4. Reviewer Agent - 质量审阅
    reviewer_llm = build_chat_llm(task_name="reviewer")
    reviewer_tools = [review_draft_tool]
    reviewer_llm_forced = reviewer_llm.bind_tools(
        reviewer_tools,
        tool_choice={"type": "function", "function": {"name": "review_draft_tool"}}
    )
    reviewer_runnable = create_agent(
        model=reviewer_llm_forced,
        tools=reviewer_tools,
        system_prompt=REVIEWER_AGENT_PROMPT,
    )
    reviewer_agent = CompiledSubAgent(
        name="reviewer_agent",
        description=REVIEWER_AGENT_DESCRIPTION,
        runnable=reviewer_runnable,
    )

    # 5. Assembler Agent - 组装输出
    # 已重构为 StateGraph SubAgent (see subagents/assembler.py)
    # assembler_agent 已导入


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
