"""Reviewer Sub-Agent Module"""
from __future__ import annotations

import logging
import operator
import re
import json
from typing import TypedDict, Annotated, Sequence, Any

from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from deepagents import CompiledSubAgent

from ..tools import (
    validate_result_tool
)
from ..prompts import (
    REVIEWER_AGENT_DESCRIPTION
)

_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Reviewer Agent Definition
# -------------------------------------------------------------------------

class ReviewerAgentState(TypedDict):
    """Reviewer Agent 的状态"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    task_description: str
    analysis_id: str
    validation_result: str
    review_decision: str

def reviewer_step1_validate(state: ReviewerAgentState, config: RunnableConfig) -> dict:
    """Step 1: 调用 validate_result_tool 检查数据"""
    _LOGGER.info("[Reviewer Agent Fixed Flow] Step 1: validate_result")
    
    # Check for user_id and analysis_id from config
    user_id = config.get("configurable", {}).get("user_id", "NOT_FOUND")
    analysis_id = config.get("configurable", {}).get("analysis_id", "")

    
    task_description = ""
    messages = state.get("messages", [])
    if messages:
        task_description = str(messages[-1].content)
        

    
    try:
        child_config = config.copy() if config else {}
        child_config.setdefault("metadata", {})["sub_agent"] = "Reviewer Agent"
        result = validate_result_tool.invoke({"data_source": "result", "analysis_id": analysis_id}, config=child_config)
        _LOGGER.info("[Reviewer Agent] validate_result: %s", result[:500] if len(result) > 500 else result)
        return {"validation_result": result, "analysis_id": analysis_id, "task_description": task_description}
    except Exception as e:
        _LOGGER.error("[Reviewer Agent] validate_result failed: %s", e)
        return {"validation_result": f'{{"valid": false, "error": "{e}"}}', "analysis_id": analysis_id, "task_description": task_description}

def reviewer_step2_evaluate(state: ReviewerAgentState) -> dict:
    """Step 2: 根据验证结果判断是否通过"""
    _LOGGER.info("[Reviewer Agent Fixed Flow] Step 2: evaluate")
    validation_result = state.get("validation_result", "{}")
    
    import json
    try:
        result = json.loads(validation_result)
    except:
        result = {"valid": False, "error": "Invalid JSON"}
    
    valid = result.get("valid", False)
    warnings = result.get("warnings", [])
    
    if valid:
        decision = "REVIEWER_AGENT_COMPLETE: 数据校验通过，可以进行画图"
    elif warnings:
        # 检查是否有 Decimal 类型警告
        dtype_warning = [w for w in warnings if "Decimal" in w or "float" in w]
        if dtype_warning:
            decision = f"REVIEWER_AGENT_FAIL: 数据类型需要修复。请 Python Agent 将数值列转换为 float 类型。详情: {dtype_warning}"
        else:
            decision = f"REVIEWER_AGENT_FAIL: 数据质量问题。警告: {warnings}"
    else:
        decision = f"REVIEWER_AGENT_FAIL: 验证失败。错误: {result.get('error', '未知错误')}"
    
    _LOGGER.info("[Reviewer Agent] Decision: %s", decision)
    return {"review_decision": decision}

def reviewer_format_output(state: ReviewerAgentState) -> dict:
    """格式化最终输出"""
    decision = state.get("review_decision", "REVIEWER_AGENT_COMPLETE: 数据校验通过")
    return {"messages": [AIMessage(content=decision)]}

# 构建 Reviewer 固化流程图
reviewer_agent_graph = StateGraph(ReviewerAgentState)
reviewer_agent_graph.add_node("validate", reviewer_step1_validate)
reviewer_agent_graph.add_node("evaluate", reviewer_step2_evaluate)
reviewer_agent_graph.add_node("format_output", reviewer_format_output)

reviewer_agent_graph.add_edge(START, "validate")
reviewer_agent_graph.add_edge("validate", "evaluate")
reviewer_agent_graph.add_edge("evaluate", "format_output")
reviewer_agent_graph.add_edge("format_output", END)

reviewer_agent_runnable = reviewer_agent_graph.compile()

reviewer_agent = CompiledSubAgent(
    name="reviewer_agent",
    description=REVIEWER_AGENT_DESCRIPTION,
    runnable=reviewer_agent_runnable,
)
