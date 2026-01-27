"""Report Sub-Agent Module"""
from __future__ import annotations

import logging
import operator
import os
import re
import json
from typing import TypedDict, Annotated, Sequence, Any

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from deepagents import CompiledSubAgent

from agent_core.runtime import build_chat_llm
from ..tools import (
    df_profile_tool
)
from ..utils.artifacts import load_report, save_report, get_dataframe
from ..prompts import (
    REPORT_AGENT_DESCRIPTION
)

from agent_core.decorators import node_wrapper

_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Report Agent Definition
# -------------------------------------------------------------------------

class ReportAgentState(TypedDict):
    """Report Agent 的状态"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    task_description: str
    analysis_id: str
    df_profile_result: str
    report_content: str

@node_wrapper("report_df_profile", graph_id="report_agent")
def report_step1_df_profile(state: ReportAgentState, config: RunnableConfig) -> dict:
    """Step 1: 强制调用 df_profile 获取数据概览"""
    _LOGGER.info("[Report Agent Fixed Flow] Step 1: df_profile")
    
    # Check for user_id and analysis_id from config
    user_id = config.get("configurable", {}).get("user_id", "NOT_FOUND")
    analysis_id = config.get("configurable", {}).get("analysis_id", "")

    
    task_description = ""
    messages = state.get("messages", [])
    if messages:
        task_description = str(messages[-1].content)
    

    
    try:
        # 1. 强制调用 df_profile 获取基础信息
        child_config = config.copy() if config else {}
        child_config.setdefault("metadata", {})["sub_agent"] = "Report Agent"
        profile_json = df_profile_tool.invoke({"df_name": "result", "analysis_id": analysis_id}, config=child_config)
        
        # 2. 增强：加载完整数据并转换为 Markdown 表格供给 LLM
        # from ..utils.dataframe_store import get_dataframe # IMPORTED ABOVE
        
        full_data_str = "（数据加载失败）"
        try:
            df = get_dataframe("result", analysis_id, user_id)
            if df is not None and not df.empty:
                # 限制最大行数，防止暴撑 Context (例如最多 100 行)
                if len(df) > 100:
                     _LOGGER.info("[Report Agent] DataFrame too large (%d rows), taking top 100.", len(df))
                     df_display = df.head(100)
                     footer = f"\n... (剩余 {len(df)-100} 行数据已省略)"
                else:
                     df_display = df
                     footer = ""
                
                full_data_str = df_display.to_markdown(index=False) + footer
                _LOGGER.info("[Report Agent] Full data prepared (%d chars)", len(full_data_str))
        except Exception as load_err:
            _LOGGER.error("[Report Agent] Full data load failed: %s", load_err)
            full_data_str = f"数据加载错误: {load_err}"

        # 合并结果
        full_result = f"【基本概览】\n{profile_json}\n\n【完整详细数据】\n{full_data_str}"

        return {"df_profile_result": full_result, "analysis_id": analysis_id, "task_description": task_description}
    except Exception as e:
        _LOGGER.error("[Report Agent] df_profile failed: %s", e)
        return {"df_profile_result": f"Error: {e}", "analysis_id": analysis_id, "task_description": task_description}

@node_wrapper("report_generate", graph_id="report_agent")
def report_step2_generate(state: ReportAgentState, config: RunnableConfig) -> dict:
    """Step 2: LLM 根据数据概览生成 Markdown 报告"""
    _LOGGER.info("[Report Agent Fixed Flow] Step 2: LLM generate report")
    task = state.get("task_description", "")
    df_info = state.get("df_profile_result", "")
    analysis_id = state.get("analysis_id", "")
    user_id = "anonymous"
    if config:
        user_id = config.get("configurable", {}).get("user_id", "anonymous")
    
    # 🚀 读取之前的报告（如果存在），支持增量修改
    prev_report = ""
    prev_report_section = ""
    if analysis_id and user_id:
        prev_report = load_report(analysis_id, user_id=user_id)
        if prev_report:
            _LOGGER.info("[Report Agent] Loaded previous report (%d chars) for incremental modification", len(prev_report))
            prev_report_section = f"""
【上一个版本的报告】
以下是之前生成的报告，用户可能对此有反馈。请根据任务描述中的用户反馈进行修改。

{prev_report}

"""
    
    prompt = f"""你是 Report Agent，负责生成数据分析报告。

【任务描述】
{task}
{prev_report_section}
【真实数据样本】
{df_info}

【报告要求】
- 基于真实数据样本进行描述，严禁编造数据
- 输出纯 Markdown 格式（以 # 标题开始）

【默认章节结构】
# 最终分析报告
## 执行摘要（数据规模、时间范围、关键发现）
## 数据概览（列名和数据类型）
## 详细分析（数值统计描述）
## 结论

【重要】如果任务描述中包含"用户反馈"，你必须严格遵守用户的修改要求：
- "去掉 XXX" / "删除 XXX" → 在新报告中不输出该章节
- "添加 XXX" / "增加 XXX" → 在新报告中新增该章节内容
- "修改 XXX" → 按照用户要求修改对应内容
- 用户的反馈是最高优先级，务必完全按照反馈执行
"""
    # 获取 LLM
    llm = build_chat_llm(task_name="report_agent")
    
    # Use Standard Content Block
    from ..utils.message_utils import extract_text_from_message
    
    messages = [HumanMessage(content=[
        {"type": "text", "text": prompt}
    ])]
    
    # 🚀 使用流式输出 + with_config 设置 tags，让 metadata 包含 agent 名称
    llm_config = {"tags": ["agent:report_agent"], "metadata": {"sub_agent": "Report Agent"}}
    full_response = None
    for chunk in llm.with_config(llm_config).stream(messages):
        if full_response is None:
            full_response = chunk
        else:
            full_response += chunk
    response = full_response
    
    content = extract_text_from_message(response)
    _LOGGER.info("[Report Agent] LLM generated report content length: %d", len(content))
    
    # 🚀 过滤思考内容：移除 <think>...</think> 标签及其内容
    # 支持多种格式：<think>, </think>, 以及可能的变体
    think_pattern = r'<think>.*?</think>'
    content = re.sub(think_pattern, '', content, flags=re.DOTALL | re.IGNORECASE)
    
    # 清理多余的空行
    content = re.sub(r'\n{3,}', '\n\n', content).strip()
    
    _LOGGER.info("[Report Agent] Filtered thinking content, final length: %d", len(content))
    
    # 持久化报告到文件
    analysis_id = state.get("analysis_id", "")
    user_id = "anonymous"
    if config:
        user_id = config.get("configurable", {}).get("user_id", "anonymous")
    
    if analysis_id:
        try:
            saved_path = save_report(content, analysis_id, user_id=user_id)
            _LOGGER.info("[Report Agent] Report saved to: %s", saved_path)
        except Exception as e:
            _LOGGER.error("[Report Agent] Failed to save report: %s", e)
    
    # 直接返回最终消息，通过 subgraph streaming 传给前端
    # 格式: REPORT_AGENT_COMPLETE: {"type": "report", "content": "..."}
    report_message = json.dumps({"type": "report", "content": content}, ensure_ascii=False)
    return {"messages": [AIMessage(content=f"REPORT_AGENT_COMPLETE: {report_message}")]}

# 构建 Report 固化流程图
report_agent_graph = StateGraph(ReportAgentState)
report_agent_graph.add_node("report_df_profile", report_step1_df_profile)
report_agent_graph.add_node("report_generate", report_step2_generate)

report_agent_graph.add_edge(START, "report_df_profile")
report_agent_graph.add_edge("report_df_profile", "report_generate")
report_agent_graph.add_edge("report_generate", END)

report_agent_runnable = report_agent_graph.compile()

report_agent = CompiledSubAgent(
    name="report_agent",
    description=REPORT_AGENT_DESCRIPTION,
    runnable=report_agent_runnable,
)
