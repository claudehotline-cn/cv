"""Assembler Sub-Agent Module"""
from __future__ import annotations

import logging
import operator
import json
from typing import TypedDict, Annotated, Sequence, Any

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from deepagents import CompiledSubAgent

from ..tools.assembler import assemble_article_tool
from ..prompts import ASSEMBLER_AGENT_DESCRIPTION

_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Assembler Agent Definition (StateGraph / Logic-First)
# -------------------------------------------------------------------------

class AssemblerAgentState(TypedDict):
    """Assembler Agent 的状态"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    article_id: str
    assembler_result: dict

def assembler_step_assemble(state: AssemblerAgentState, config: RunnableConfig) -> dict:
    """Step 1: 直接调用 assemble_article_tool"""
    _LOGGER.info("[Assembler Agent] Step 1: Executing assemble_article_tool")
    
    # 从 config 或 state 获取 context
    # 注意: article_id 现在推荐从 session_id/task_id 机制获取，这里为了兼容旧逻辑尝试从 config 读
    # 但 tool 内部会尝试 article_id -> artifacts 路径
    
    # 尝试从 messages 中提取 article_id (Main Agent 可能传递了)
    # 但最可靠的是从 runtime config
    article_id = config.get("configurable", {}).get("article_id")
    if not article_id:
        # 尝试从 session_id 映射 (如果 session_id == article_id)
        article_id = config.get("configurable", {}).get("session_id")
    
    title = "Generated Article" # 默认，tool 会尝试从 outline 恢复
    
    try:
        # 直接调用 Tool 函数逻辑 (Runable invoke)
        # 传入必要参数，其他参数 tool 会自动处理(如路径发现)
        result = assemble_article_tool.invoke(
            {
                "article_id": article_id, 
                "title": title, 
                "final_markdown_path": "" # 留空让工具自动发现
            }, 
            config=config
        )
        
        return {"assembler_result": result, "article_id": article_id}
        
    except Exception as e:
        _LOGGER.error(f"[Assembler Agent] Assembly failed: {e}")
        return {"assembler_result": {"error": str(e)}, "article_id": article_id}

def assembler_step_format(state: AssemblerAgentState, config: RunnableConfig) -> dict:
    """Step 2: 格式化输出为 subgraph streaming 消息"""
    _LOGGER.info("[Assembler Agent] Step 2: Formatting output")
    
    result = state.get("assembler_result", {})
    article_content = result.get("article_content", "")
    md_path = result.get("md_path", "")
    
    # 构建完整 payload
    payload = {
        "type": "article",
        "content": article_content,
        "md_path": md_path,
        "article_id": state.get("article_id")
    }
    
    # 序列化
    payload_str = json.dumps(payload, ensure_ascii=False)
    
    # 返回特殊格式消息
    return {"messages": [AIMessage(content=f"ASSEMBLER_AGENT_COMPLETE: {payload_str}")]}

# 构建 Graph
assembler_graph = StateGraph(AssemblerAgentState)
assembler_graph.add_node("assemble", assembler_step_assemble)
assembler_graph.add_node("format", assembler_step_format)

assembler_graph.add_edge(START, "assemble")
assembler_graph.add_edge("assemble", "format")
assembler_graph.add_edge("format", END)

assembler_runnable = assembler_graph.compile()

assembler_agent = CompiledSubAgent(
    name="assembler_agent",
    description=ASSEMBLER_AGENT_DESCRIPTION,
    runnable=assembler_runnable,
)
