"""统一数据分析 Deep Agent (Multi-Agent Version)：基于 deepagents 实现的分层多智能体系统。"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents import create_agent
from deepagents import create_deep_agent, CompiledSubAgent
from deepagents.backends import CompositeBackend, FilesystemBackend, StoreBackend
from deepagents.backends import CompositeBackend, FilesystemBackend, StoreBackend
from ..llm_runtime import build_chat_llm
from ..middleware import StructuredOutputToTextMiddleware, ThinkingLoggerMiddleware, AnalysisIDMiddleware
from .tools import (
    db_list_tables_tool, db_table_schema_tool, db_run_sql_tool,
    excel_list_sheets_tool, excel_load_tool,
    python_execute_tool, df_profile_tool, validate_result_tool,
    generate_chart_tool, clear_dataframes
)
from .prompts import (
    MAIN_AGENT_PROMPT,
    SQL_AGENT_DESCRIPTION, SQL_AGENT_PROMPT,
    EXCEL_AGENT_DESCRIPTION, EXCEL_AGENT_PROMPT,
    PYTHON_AGENT_DESCRIPTION, PYTHON_AGENT_PROMPT,
    REVIEWER_AGENT_DESCRIPTION, REVIEWER_AGENT_PROMPT,
    VISUALIZER_AGENT_DESCRIPTION, VISUALIZER_AGENT_PROMPT,
    STATISTICS_AGENT_DESCRIPTION, STATISTICS_AGENT_PROMPT,
    ML_AGENT_DESCRIPTION, ML_AGENT_PROMPT,
    REPORT_AGENT_DESCRIPTION, REPORT_AGENT_PROMPT,
)

_LOGGER = logging.getLogger("agent_langchain.data_deep_graph")


def _compile_subagent(
    name: str,
    description: str,
    system_prompt: str,
    tools: list,
    model: Any,
    middleware: list | None = None,
    tool_choice: str | dict | None = None
) -> CompiledSubAgent:
    """编译一个 SubAgent 为 CompiledSubAgent。"""
    if tool_choice:
        model = model.bind_tools(tools, tool_choice=tool_choice)
        
    runnable = create_agent(
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        middleware=middleware or [],
    )
    return CompiledSubAgent(
        name=name,
        description=description,
        runnable=runnable
    )


def get_data_deep_agent_graph() -> Any:
    """构造并返回统一的数据分析 Deep Agent (Multi-Agent 架构)。"""
    
    # 清空之前的 DataFrame 缓存（现在是文件系统）
    # clear_dataframes 需要 analysis_id，这里跳过
    
    # 统一使用 qwen3:30b 模型
    main_llm = build_chat_llm(task_name="data_deep_main")
    subagent_llm = build_chat_llm(task_name="data_deep_subagent")
    
    # 默认中间件
    default_middleware = [StructuredOutputToTextMiddleware()]
    
    # ============================================================================
    # 编译子 Agent (CompiledSubAgent)
    # ============================================================================
    
    # 1. SQL Agent
    sql_agent = _compile_subagent(
        name="sql_agent",
        description=SQL_AGENT_DESCRIPTION,
        system_prompt=SQL_AGENT_PROMPT,
        tools=[db_list_tables_tool, db_table_schema_tool, db_run_sql_tool],
        model=subagent_llm,
    )
    
    # 2. Excel Agent
    excel_agent = _compile_subagent(
        name="excel_agent",
        description=EXCEL_AGENT_DESCRIPTION,
        system_prompt=EXCEL_AGENT_PROMPT,
        tools=[excel_list_sheets_tool, excel_load_tool],
        model=subagent_llm,
    )
    
    # 3. Python Agent
    python_agent = _compile_subagent(
        name="python_agent",
        description=PYTHON_AGENT_DESCRIPTION,
        system_prompt=PYTHON_AGENT_PROMPT,
        tools=[python_execute_tool],
        model=subagent_llm,
    )
    
    # 4. Reviewer Agent - 使用 Article Agent 模式：先绑定工具，再创建 agent
    reviewer_llm = build_chat_llm(task_name="data_deep_reviewer")
    reviewer_tools = [validate_result_tool]
    
    # 强制调用指定工具（使用具体工具名，而非 "any"）
    reviewer_llm_forced = reviewer_llm.bind_tools(
        reviewer_tools,
        tool_choice={"type": "function", "function": {"name": "validate_result_tool"}}
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
    
    # 5. Visualizer Agent
    visualizer_agent = _compile_subagent(
        name="visualizer_agent",
        description=VISUALIZER_AGENT_DESCRIPTION,
        system_prompt=VISUALIZER_AGENT_PROMPT,
        tools=[python_execute_tool],
        model=subagent_llm,
        middleware=default_middleware,
    )
    
    # 6. Statistics Agent
    statistics_agent = _compile_subagent(
        name="statistics_agent",
        description=STATISTICS_AGENT_DESCRIPTION,
        system_prompt=STATISTICS_AGENT_PROMPT,
        tools=[df_profile_tool, python_execute_tool],
        model=subagent_llm,
    )
    
    # 7. ML Agent
    ml_agent = _compile_subagent(
        name="ml_agent",
        description=ML_AGENT_DESCRIPTION,
        system_prompt=ML_AGENT_PROMPT,
        tools=[df_profile_tool, python_execute_tool],
        model=subagent_llm,
    )
    
    # 8. Report Agent
    report_agent = _compile_subagent(
        name="report_agent",
        description=REPORT_AGENT_DESCRIPTION,
        system_prompt=REPORT_AGENT_PROMPT,
        tools=[df_profile_tool, python_execute_tool],
        model=subagent_llm,
    )
    
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
            visualizer_agent, statistics_agent, ml_agent, report_agent
        ],
        tools=[],
        system_prompt=MAIN_AGENT_PROMPT,
        middleware=[ThinkingLoggerMiddleware(), AnalysisIDMiddleware(), StructuredOutputToTextMiddleware()],
        backend=lambda rt: CompositeBackend(
            default=FilesystemBackend(root_dir="/data/workspace", virtual_mode=True),
            routes={"/_shared/": StoreBackend(rt)},
        ),
        response_format=response_format,
    )
    
    return graph
