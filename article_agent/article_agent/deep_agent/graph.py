"""Article Deep Agent (Multi-Agent Version)：基于 deepagents 实现的分层多智能体文章生成系统。"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent, SubAgent
from deepagents.backends import CompositeBackend, FilesystemBackend, StoreBackend
from langgraph.store.memory import InMemoryStore

# 进程级别共享 Store 实例，用于跨线程数据共享
_shared_store = InMemoryStore()

from ..config.llm_runtime import build_chat_llm
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
    ASSEMBLER_AGENT_PROMPT,
    ASSEMBLER_AGENT_DESCRIPTION,
    INGEST_AGENT_PROMPT,
    INGEST_AGENT_DESCRIPTION,
)
from .middleware import ArticleContentMiddleware, ThinkingLoggerMiddleware, AssemblerStateMiddleware, PDFAttachmentMiddleware
from .schemas import ArticleAgentOutput, AssemblerOutput
from .tools import (
    # Collector tools
    # Collector tools
    # fetch_url_tool,
    load_file_tool,
    # collect_all_sources_tool,
    ingest_documents_tool,
    # Planner tools
    generate_outline_tool,
    # Researcher tools
    read_sources_tool,
    research_section_tool,
    research_all_sections_tool,
    research_audit_tool,
    # Writer tools
    write_section_tool,
    write_all_sections_tool,
    writer_audit_tool,
    # Reviewer tools
    review_draft_tool,
    # Reviewer tools
    review_draft_tool,
    # Assembler tools
    assemble_article_tool,
)

_LOGGER = logging.getLogger("article_agent.article_deep_graph")



def get_article_deep_agent_graph() -> Any:
    """构造并返回 Article Deep Agent (Multi-Agent 架构)。
    
    入口函数，被 langgraph.json 引用。
    """
    # 创建思维链日志 middleware
    thinking_middleware = ThinkingLoggerMiddleware()

    
    # 使用配置的 LLM
    # 恢复推理模式 - 禁用推理会导致工具调用生成失败
    main_llm = build_chat_llm(task_name="article_deep_main")
    
    # ============================================================================
    # 定义子 Agent (Sub-Agents)
    # ============================================================================
    
    # 0. Ingest Agent - 素材采集
    ingest_agent = SubAgent(
        name="ingest_agent",
        description=INGEST_AGENT_DESCRIPTION,
        system_prompt=INGEST_AGENT_PROMPT,
        tools=[ingest_documents_tool],
    )

    # 1. Planner Agent - 大纲规划 (不再负责收集)
    planner_agent = SubAgent(
        name="planner_agent",
        description=PLANNER_AGENT_DESCRIPTION,
        system_prompt=PLANNER_AGENT_PROMPT,
        tools=[generate_outline_tool, load_file_tool],
    )
    
    # 2. Researcher Agent - 资料整理
    researcher_agent = SubAgent(
        name="researcher_agent",
        description=RESEARCHER_AGENT_DESCRIPTION,
        system_prompt=RESEARCHER_AGENT_PROMPT,
        tools=[read_sources_tool, research_section_tool, research_all_sections_tool, research_audit_tool],
    )
    
    # 4. Writer Agent - 内容撰写
    writer_agent = SubAgent(
        name="writer_agent",
        description=WRITER_AGENT_DESCRIPTION,
        system_prompt=WRITER_AGENT_PROMPT,
        tools=[write_section_tool, write_all_sections_tool, writer_audit_tool],
    )
    
    # 5. Reviewer Agent - 质量审阅
    reviewer_agent = SubAgent(
        name="reviewer_agent",
        description=REVIEWER_AGENT_DESCRIPTION,
        system_prompt=REVIEWER_AGENT_PROMPT,
        tools=[review_draft_tool],
    )
    

    
    # 配置 Assembler 的结构化输出
    try:
        from langchain.agents.structured_output import ToolStrategy
        assembler_response_format = ToolStrategy(AssemblerOutput)
    except ImportError:
        assembler_response_format = AssemblerOutput

    # 7. Assembler Agent - 组装输出
    assembler_agent = SubAgent(
        name="assembler_agent",
        description=ASSEMBLER_AGENT_DESCRIPTION,
        system_prompt=ASSEMBLER_AGENT_PROMPT,
        tools=[assemble_article_tool],
        response_format=assembler_response_format,  # Enable structured output via ToolStrategy
        middleware=[AssemblerStateMiddleware()], # Write md_path to State for Main Agent Middleware to read
    )

    # ============================================================================
    # 创建主 Deep Agent
    # ============================================================================
    
    try:
        from langchain.agents.structured_output import ToolStrategy
        response_format = ToolStrategy(ArticleAgentOutput)
    except ImportError:
        response_format = ArticleAgentOutput
    
    # 创建 Deep Agent
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
        tools=[],  # Main Agent 不直接使用工具，通过 SubAgents 执行
        system_prompt=MAIN_AGENT_PROMPT,
        middleware=[thinking_middleware, ArticleContentMiddleware()],  # 思维链日志、内容填充
        backend=lambda rt: CompositeBackend(
            default=FilesystemBackend(
                root_dir="/data/workspace",
                virtual_mode=True  # 沙箱模式：限制文件操作在 root_dir 内，防止访问 /proc 等系统路径
            ),
            routes={
                "/_shared/": StoreBackend(rt),  # 跨线程共享路径
            }
        ),
        store=_shared_store,  # 传入共享的 Store 实例
        response_format=response_format,  # 启用结构化输出
    )
    
    _LOGGER.info("Article Deep Agent graph created with 6 SubAgents")
    
    return graph


__all__ = ["get_article_deep_agent_graph"]
