"""统一数据分析 Deep Agent (Multi-Agent Version)：基于 deepagents 实现的分层多智能体系统。"""

from __future__ import annotations

import logging
from typing import Any, List, Dict

from deepagents import create_deep_agent, SubAgent
from .llm_runtime import build_chat_llm
from .data_deep_tools import (
    # DB Tools
    db_list_tables_tool,
    db_table_schema_tool,
    db_run_sql_tool,
    # Excel Tools
    excel_list_sheets_tool,
    excel_load_tool,
    # Python Tools
    python_execute_tool,
    clear_dataframes,
    # Chart Tools
    generate_chart_tool,
    # Validation Tools
    validate_result_tool,
    # New Profile Tool
    df_profile_tool
)
from .data_deep_prompts import (
    MAIN_AGENT_PROMPT,
    SQL_AGENT_DESCRIPTION, SQL_AGENT_PROMPT,
    EXCEL_AGENT_DESCRIPTION, EXCEL_AGENT_PROMPT,
    PYTHON_AGENT_DESCRIPTION, PYTHON_AGENT_PROMPT,
    REVIEWER_AGENT_DESCRIPTION, REVIEWER_AGENT_PROMPT,
    CHART_AGENT_DESCRIPTION, CHART_AGENT_PROMPT,
    VISUALIZER_AGENT_DESCRIPTION, VISUALIZER_AGENT_PROMPT
)
# from .visualizer_tools import ... (Deleted)
# from .visualizer_schemas import ... (Deleted)

_LOGGER = logging.getLogger("agent_langchain.data_deep_graph")

def get_data_deep_agent_graph() -> Any:
    """构造并返回统一的数据分析 Deep Agent (Multi-Agent 架构)。
    
    入口函数，被 langgraph.json 引用。
    """
    
    # 清空之前的 DataFrame 缓存
    clear_dataframes()
    
    # 统一使用 qwen3:30b 模型 (配置在 .env 或 build_chat_llm默认)
    main_llm = build_chat_llm(task_name="data_deep_main")
    
    # ============================================================================
    # 定义子 Agent (Sub-Agents)
    # ============================================================================
    
    # 1. SQL Agent
    sql_agent = SubAgent(
        name="sql_agent",
        description=SQL_AGENT_DESCRIPTION,
        system_prompt=SQL_AGENT_PROMPT,
        tools=[db_list_tables_tool, db_table_schema_tool, db_run_sql_tool]
    )
    
    # 2. Excel Agent
    excel_agent = SubAgent(
        name="excel_agent",
        description=EXCEL_AGENT_DESCRIPTION,
        system_prompt=EXCEL_AGENT_PROMPT,
        tools=[excel_list_sheets_tool, excel_load_tool]
    )
    
    # 3. Python Agent
    python_agent = SubAgent(
        name="python_agent",
        description=PYTHON_AGENT_DESCRIPTION,
        system_prompt=PYTHON_AGENT_PROMPT,
        tools=[df_profile_tool, python_execute_tool]
    )
    
    # 4. Reviewer Agent (质检员)
    reviewer_agent = SubAgent(
        name="reviewer_agent",
        description=REVIEWER_AGENT_DESCRIPTION,
        system_prompt=REVIEWER_AGENT_PROMPT,
        tools=[validate_result_tool]
    )

    # 5. Chart Agent (Legacy - DISABLED, replaced by visualizer_agent)
    from .middleware import StructuredOutputToTextMiddleware
    # chart_agent = SubAgent(
    #     name="chart_agent",
    #     description=CHART_AGENT_DESCRIPTION,
    #     system_prompt=CHART_AGENT_PROMPT,
    #     tools=[generate_chart_tool, python_execute_tool],
    #     middleware=[StructuredOutputToTextMiddleware()],
    # )
    
    # 6. Visualizer Agent (Profile + Python Architecture)
    # Uses viz_df_profile to inspect data, python_execute to generate chart with CHART_DATA: prefix
    visualizer_agent = SubAgent(
        name="visualizer_agent",
        description=VISUALIZER_AGENT_DESCRIPTION,
        system_prompt=VISUALIZER_AGENT_PROMPT,
        tools=[df_profile_tool, python_execute_tool],  # Only 2 tools
        middleware=[StructuredOutputToTextMiddleware()],
    )
    
    # ============================================================================
    # 创建主 Deep Agent
    # ============================================================================
    from .schemas import MainAgentOutput
    try:
        from langchain.agents.structured_output import ToolStrategy
        response_format = ToolStrategy(MainAgentOutput)
    except ImportError:
        # Fallback for older versions or if ToolStrategy is not explicit
        response_format = MainAgentOutput

    graph = create_deep_agent(
        model=main_llm,
        subagents=[sql_agent, excel_agent, python_agent, reviewer_agent, visualizer_agent],
        tools=[],  
        system_prompt=MAIN_AGENT_PROMPT,
        middleware=[StructuredOutputToTextMiddleware()], # Apply same middleware to main agent
        response_format=response_format, # Enable structured output for Main Agent
    )
    
    return graph
