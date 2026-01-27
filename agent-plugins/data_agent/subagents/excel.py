"""Excel Sub-Agent Module"""
from __future__ import annotations

import logging
import operator
import re
from typing import TypedDict, Annotated, Sequence, Any

from langchain_core.messages import BaseMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from deepagents import CompiledSubAgent

from ..tools import (
    excel_list_sheets_tool, excel_load_tool
)
from ..prompts import (
    EXCEL_AGENT_DESCRIPTION
)

from agent_core.decorators import node_wrapper

_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Excel Agent Definition
# -------------------------------------------------------------------------

class ExcelAgentState(TypedDict):
    """Excel Agent 的状态"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    task_description: str
    analysis_id: str
    file_id: str
    sheets_info: str       # Step 1: Sheet 列表
    load_result: str       # Step 2: 加载结果

@node_wrapper("list_sheets", graph_id="excel_agent")
def excel_step1_list_sheets(state: ExcelAgentState, config: RunnableConfig) -> dict:
    """Step 1: 列出 Excel Sheet"""
    _LOGGER.info("[Excel Agent Fixed Flow] Step 1: list_sheets")
    
    # Check for user_id and analysis_id from config
    user_id = config.get("configurable", {}).get("user_id", "NOT_FOUND")
    analysis_id = config.get("configurable", {}).get("analysis_id", "")

    
    file_id = ""
    task_description = ""
    
    messages = state.get("messages", [])
    for msg in messages:
        content = getattr(msg, "content", "") if hasattr(msg, "content") else str(msg)
        # 提取 file_id
        match_fid = re.search(r'\[file_id[=:]?\s*([^\]]+)\]', content, re.IGNORECASE)
        if match_fid:
            file_id = match_fid.group(1).strip()
        task_description = content

    if not file_id:
        return {"sheets_info": "Error: No file_id provided", "analysis_id": analysis_id, "file_id": file_id, "task_description": task_description}

    try:
        # 调用 list_sheets_tool (假设有 file_id 参数支持)
        result = excel_list_sheets_tool.invoke({"file_id": file_id})
        _LOGGER.info("[Excel Agent] list_sheets result: %s", result[:300] if len(result) > 300 else result)
        return {"sheets_info": result, "analysis_id": analysis_id, "file_id": file_id, "task_description": task_description}
    except Exception as e:
        _LOGGER.error("[Excel Agent] list_sheets failed: %s", e)
        return {"sheets_info": f"Error: {e}", "analysis_id": analysis_id, "file_id": file_id, "task_description": task_description}

@node_wrapper("load_sheet", graph_id="excel_agent")
def excel_step2_load_sheet(state: ExcelAgentState, config: RunnableConfig) -> dict:
    """Step 2: 加载 Sheet 数据"""
    _LOGGER.info("[Excel Agent Fixed Flow] Step 2: load_sheet")
    
    file_id = state.get("file_id", "")
    analysis_id = state.get("analysis_id", "")
    
    # 默认加载第一个 Sheet (Sheet1 或索引0)
    sheet_name = "Sheet1"
    
    try:
        result = excel_load_tool.invoke({
            "file_id": file_id,
            "sheet_name": sheet_name,
            "analysis_id": analysis_id
        })
        _LOGGER.info("[Excel Agent] load_sheet result: %s", result[:300] if len(result) > 300 else result)
        return {"load_result": result}
    except Exception as e:
        _LOGGER.error("[Excel Agent] load_sheet failed: %s", e)
        return {"load_result": f"Error: {e}"}

@node_wrapper("format_output", graph_id="excel_agent")
def excel_format_output(state: ExcelAgentState, config: RunnableConfig) -> dict:
    """格式化输出"""
    load_result = state.get("load_result", "")
    output = f"EXCEL_AGENT_COMPLETE: Excel 数据加载完成\n\n{load_result}"
    return {"messages": [AIMessage(content=output)]}

# 构建 Excel 固化流程图
excel_agent_graph = StateGraph(ExcelAgentState)
excel_agent_graph.add_node("list_sheets", excel_step1_list_sheets)
excel_agent_graph.add_node("load_sheet", excel_step2_load_sheet)
excel_agent_graph.add_node("format_output", excel_format_output)

excel_agent_graph.add_edge(START, "list_sheets")
excel_agent_graph.add_edge("list_sheets", "load_sheet")
excel_agent_graph.add_edge("load_sheet", "format_output")
excel_agent_graph.add_edge("format_output", END)

excel_agent_runnable = excel_agent_graph.compile()

excel_agent = CompiledSubAgent(
    name="excel_agent",
    description=EXCEL_AGENT_DESCRIPTION,
    runnable=excel_agent_runnable,
)
