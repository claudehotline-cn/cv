"""Article Deep Agent (Multi-Agent Version)：基于 deepagents 实现的分层多智能体文章生成系统。"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent, SubAgent, CompiledSubAgent
from deepagents.backends import CompositeBackend, FilesystemBackend, StoreBackend
from langchain.agents import create_agent
from langgraph.store.memory import InMemoryStore
from langchain_core.runnables import RunnableLambda

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
from .middleware import ArticleContentMiddleware, ThinkingLoggerMiddleware, AssemblerStateMiddleware, PDFAttachmentMiddleware, ArticleIDMiddleware
from .schemas import ArticleAgentOutput, AssemblerOutput, IngestOutput
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
    
    # 0. Ingest Agent - 素材采集 (Structured Output + Required Tool Calling)
    ingest_llm = build_chat_llm(task_name="ingest")
    ingest_tools = [ingest_documents_tool]
    
    # 强制必须调用工具 (required)，但不锁定具体哪个工具
    # 这样 LLM 可以先调用 ingest_documents_tool（干活），再调用 IngestOutput（交差）
    ingest_llm_forced = ingest_llm.bind_tools(
        ingest_tools,
        tool_choice="required"  # 必须调用工具，但可以选择哪个
    )
    
    ingest_runnable = create_agent(
        model=ingest_llm_forced,
        tools=ingest_tools,
        system_prompt=INGEST_AGENT_PROMPT,
        response_format=IngestOutput, # 启用 Pydantic 结构化输出
    )

    ingest_agent = CompiledSubAgent(
        name="ingest_agent",
        description=INGEST_AGENT_DESCRIPTION,
        runnable=ingest_runnable,
    )

    # 1. Planner Agent - 大纲规划 (使用 CompiledSubAgent 强制调用工具)
    planner_llm = build_chat_llm(task_name="planner")
    planner_tools = [generate_outline_tool]  # 只需要这一个工具，移除未使用的 load_file_tool
    
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
    
    # 2. Researcher Agent - 资料整理 (使用 CompiledSubAgent 强制工具调用)
    # 创建一个带 tool_choice='required' 的 LLM，确保必须调用工具
    researcher_llm = build_chat_llm(task_name="researcher")
    researcher_tools = [research_all_sections_tool]  # 只需要这一个入口工具
    
    # 强制调用指定工具（使用具体工具名，而非 "required"）
    researcher_llm_forced = researcher_llm.bind_tools(
        researcher_tools,
        tool_choice={"type": "function", "function": {"name": "research_all_sections_tool"}}
    )
    
    # 创建一个预编译的 agent runnable
    researcher_runnable = create_agent(
        model=researcher_llm_forced,
        tools=researcher_tools,
        system_prompt=RESEARCHER_AGENT_PROMPT,
    )
    
    # 包装为 CompiledSubAgent
    researcher_agent = CompiledSubAgent(
        name="researcher_agent",
        description=RESEARCHER_AGENT_DESCRIPTION,
        runnable=researcher_runnable,
    )
    
    # 4. Writer Agent - 内容撰写 (使用 CompiledSubAgent 强制调用工具)
    writer_llm = build_chat_llm(task_name="writer")
    writer_tools = [write_all_sections_tool]  # 主入口工具，移除 write_section_tool 和 writer_audit_tool
    
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
    
    # 5. Reviewer Agent - 质量审阅 (使用 CompiledSubAgent 强制调用工具)
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

    # 7. Assembler Agent - 组装输出 (使用 CompiledSubAgent 强制调用工具)
    assembler_llm = build_chat_llm(task_name="assembler")
    assembler_tools = [assemble_article_tool]
    
    assembler_llm_forced = assembler_llm.bind_tools(
        assembler_tools,
        tool_choice={"type": "function", "function": {"name": "assemble_article_tool"}}
    )
    
    assembler_runnable = create_agent(
        model=assembler_llm_forced,
        tools=assembler_tools,
        system_prompt=ASSEMBLER_AGENT_PROMPT,
    )
    
    assembler_agent = CompiledSubAgent(
        name="assembler_agent",
        description=ASSEMBLER_AGENT_DESCRIPTION,
        runnable=assembler_runnable,
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
        middleware=[thinking_middleware, PDFAttachmentMiddleware(), ArticleIDMiddleware(), ArticleContentMiddleware()],  # 中间件链执行顺序
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
