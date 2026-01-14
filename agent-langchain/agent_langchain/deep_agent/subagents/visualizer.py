"""Visualizer Sub-Agent Module"""
from __future__ import annotations

import logging
import operator
import os
import re
import json
from typing import TypedDict, Annotated, Sequence, Any
from datetime import datetime

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from deepagents import CompiledSubAgent

from ...llm_runtime import build_chat_llm
from ..tools import (
    df_profile_tool, python_execute_tool
)
from ..prompts import (
    VISUALIZER_AGENT_DESCRIPTION
)

_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Visualizer Agent Definition
# -------------------------------------------------------------------------

class VisualizerAgentState(TypedDict):
    """Visualizer Agent 的状态"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    task_description: str
    analysis_id: str
    df_profile_result: str
    chart_code: str
    chart_result: str
    retry_count: int        # 重试次数
    error_feedback: str     # 错误反馈

def viz_step1_df_profile(state: VisualizerAgentState, config: RunnableConfig) -> dict:
    """Step 1: 调用 df_profile 查看数据结构"""
    _LOGGER.info("[Visualizer Agent Fixed Flow] Step 1: df_profile")
    
    # Check for user_id and analysis_id from config
    user_id = config.get("configurable", {}).get("user_id", "NOT_FOUND")
    analysis_id = config.get("configurable", {}).get("analysis_id", "")

    
    task_description = ""
    messages = state.get("messages", [])
    if messages:
        task_description = str(messages[-1].content)
        

    
    # 只加载 result（Python Agent 处理后的数据，已转换好类型）
    try:
        result = df_profile_tool.invoke({"df_name": "result", "analysis_id": analysis_id}, config=config)
        _LOGGER.info("[Visualizer Agent] df_profile(result): %s", result[:500] if len(result) > 500 else result)
        return {"df_profile_result": result, "analysis_id": analysis_id, "task_description": task_description}
    except Exception as e:
        _LOGGER.error("[Visualizer Agent] df_profile(result) failed: %s", e)
        return {"df_profile_result": f'{{"error": "DataFrame result not found: {e}"}}', "analysis_id": analysis_id, "task_description": task_description}

def viz_step2_llm_generate_code(state: VisualizerAgentState, config: RunnableConfig) -> dict:
    """Step 2: LLM 根据 df_profile 结果生成 ECharts 代码"""
    _LOGGER.info("[Visualizer Agent Fixed Flow] Step 2: LLM generate chart code")
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    task = state.get("task_description", "")
    df_info = state.get("df_profile_result", "")
    
    # 从 config 中获取 analysis_id 和 user_id
    user_id = config.get("configurable", {}).get("user_id", "mock_user_from_tool_call_999")
    analysis_id = config.get("configurable", {}).get("analysis_id", "")
    
    # 尝试读取现有的 chart.json 作为参考
    previous_chart = ""
    if analysis_id:
        chart_path = f"/data/workspace/{user_id}/artifacts/data_analysis_{analysis_id}/chart.json"
        try:
            import os
            if os.path.exists(chart_path):
                with open(chart_path, "r", encoding="utf-8") as f:
                    previous_chart = f.read().strip()
                    _LOGGER.info(f"[Visualizer Agent] Found previous chart: {len(previous_chart)} chars")
        except Exception as e:
            _LOGGER.warning(f"[Visualizer Agent] Failed to read previous chart: {e}")

    _LOGGER.info(f"[Visualizer Agent] Generating code for task: {task}")
    
    prompt = f"""你是 Visualizer Agent。当前日期: {today_str}。根据以下信息生成 ECharts 图表代码。

【🔴 核心规则 - 必须严格遵守】
1. **代码的第一行必须是**：`df = load_dataframe('result')`
2. **绝对禁止**只调用 `load_dataframe` 而不赋值。
3. 如果不赋值给 `df`，后续代码会报错。

【环境说明】
- 预定义函数: `load_dataframe(name)`
- 预定义模块: `json`

【任务信息】
任务描述: {task}
数据概览:
{df_info}
"""
    
    # 如果存在上一次的图表，添加到 Prompt 中作为参考
    if previous_chart:
        prompt += f"""
【⚠️ 修改模式 - 基于现有图表修改】
以下是上一次生成的图表配置（JSON 格式），你需要**基于此配置进行修改**，而不是从头生成。
请仔细阅读任务描述中的修改要求，只修改需要改变的部分，保留其他配置。
上一次的图表配置:
{previous_chart}
"""
    
    prompt += """
【代码结构要求】
1. **加载数据**：使用 `df = load_dataframe('result')` 加载数据
2. **构建 chart_option**：创建一个字典，包含以下字段：
   - `title.text`：图表标题
   - `tooltip.trigger`：通常为 "axis"
   - `legend.data`：图例名称列表
   - `xAxis`：X轴配置（类别轴用 category，数值轴用 value）
   - `yAxis`：Y轴配置
   - `series`：数据系列数组，每个系列包含 name、type、data
     * **注意**：`data` 必须是**列表** (List)，**严禁**使用字典 (Dictionary)！
     * 正确: `data: [10, 20, 30]` 或 `data: [["2023-01", 10], ["2023-02", 20]]`
     * 错误: `data: {"2023-01": 10, "2023-02": 20}`
3. **输出结果**：使用 `print("CHART_DATA:" + json.dumps({"success": True, "chart_type": "类型", "option": chart_option}))`

【图表类型说明】
- 折线图 (line)：series.type = "line"
- 柱状图 (bar)：series.type = "bar"
- 饼图 (pie)：series.type = "pie"，data 格式为 [{"name": "名称", "value": 数值}}, ...]，不需要 xAxis/yAxis

【样式自定义】
- **颜色**：在 series 中使用 `itemStyle.color` 指定颜色
- **线条样式**：使用 `lineStyle.color`、`lineStyle.width` 等
- **标签**：使用 `label.show`、`label.formatter` 等

【重要提示】
- 如果任务描述中包含颜色、样式等自定义要求，**必须**在代码中实现
- 例如"北京用红色"，则北京系列的 itemStyle.color 应设为红色
【常用功能指南】
- **添加平均线/最大值/最小值**：
  - **只有在任务明确要求时才添加！不要自作主张。**
  - 如果要求添加，请**优先使用 markLine**：
    - 平均线：`series[i]["markLine"] = {"data": [{"type": "average", "name": "平均值"}]}`
    - 最大值：`series[i]["markPoint"] = {"data": [{"type": "max", "name": "最大值"}]}`
    - **特定X轴位置竖线**：`series[0]["markLine"] = {"data": [{"xAxis": "2023-10", "name": "标记点"}]}`

- **语义区分**：
  - 用户说"画一条线"展示某数据趋势 -> 使用 **Series**
  - 用户说"添加一条横线/竖线/平均线"作为参考 -> 使用 **markLine**

- **关于"去掉"/"移除"/"隐藏"类指令**：找到 ECharts 中对应元素的配置项，将其 `show` 属性设为 `False`，或完全省略该配置。

【🚫 禁止事项】
1. **严禁**添加任务未要求的任何装饰（如平均线、最大最小值标记、背景色等）。
2. **严禁**使用"添加一个新 Series"的方式来实现辅助线（如平均线、竖线）。辅助线必须用 `markLine`。
3. **严禁**擅自修改数据或计算逻辑。

请根据任务描述直接生成 Python 代码："""
    # --- 重试逻辑：如果有错误反馈，添加到 Prompt ---
    error_feedback = state.get("error_feedback", "")
    if error_feedback:
        _LOGGER.warning("[Visualizer Agent] Retrying with error feedback: %s", error_feedback[:200])
        prompt += f"""
python
【上一次生成的代码执行错误】
错误信息: {error_feedback}

请修正上述代码，确保不再发生此错误。不要在代码中假定 `df` 已经存在，必须使用 `df = load_dataframe('result')`。
"""
    # ---------------------------------------------
    
    # 获取 LLM
    llm = build_chat_llm(task_name="data_deep_subagent")
    
    # Use Standard Content Block
    from ...utils.message_utils import extract_text_from_message
    
    messages = [HumanMessage(content=[
        {"type": "text", "text": prompt}
    ])]
    
    response = llm.invoke(messages)
    code = extract_text_from_message(response)
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0]
    elif "```" in code:
        code = code.split("```")[1].split("```")[0]
    
    _LOGGER.info("[Visualizer Agent] LLM generated code: %s", code[:300])
    return {"chart_code": code.strip()}

def viz_step3_python_execute(state: VisualizerAgentState, config: RunnableConfig) -> dict:
    """Step 3: 执行 Python 代码"""
    _LOGGER.info("[Visualizer Agent Fixed Flow] Step 3: python_execute")
    code = state.get("chart_code", "")
    analysis_id = state.get("analysis_id", "")
    
    if not code:
        return {"chart_result": "Error: No code to execute", "retry_count": 0}
        
    retry_count = state.get("retry_count", 0)
    
    try:
        result = python_execute_tool.invoke({"code": code, "analysis_id": analysis_id}, config=config)
        _LOGGER.info("[Visualizer Agent] python_execute result: %s", result[:500] if len(result) > 500 else result)
        
        # 检查执行结果是否包含错误
        is_success = True
        error_msg = ""
        try:
            res_json = json.loads(result) if isinstance(result, str) else result
            
            # 1. 检查代码执行层面是否成功
            if isinstance(res_json, dict) and not res_json.get("success", False):
                is_success = False
                error_msg = res_json.get("error", "Unknown execution error")
            
            # 2. 🔥 核心校验：必须包含 CHART_DATA 且 JSON 有效
            if is_success:
                stdout = res_json.get("stdout", "")
                if "CHART_DATA:" not in stdout:
                    is_success = False
                    error_msg = "代码执行成功，但未输出 'CHART_DATA:'。请确保使用 print('CHART_DATA:' + json.dumps(...)) 输出结果。"
                else:
                    try:
                        chart_part = stdout.split("CHART_DATA:", 1)[1].strip()
                        chart_json = json.loads(chart_part)
                        # 简单校验 option 字段
                        if "option" not in chart_json:
                            is_success = False
                            error_msg = "CHART_DATA JSON 中缺少 'option' 字段。"
                    except json.JSONDecodeError:
                        is_success = False
                        error_msg = "CHART_DATA 之后的 JSON 格式无效，无法解析。"
                    except Exception as e:
                        is_success = False
                        error_msg = f"CHART_DATA 验证异常: {str(e)}"

        except Exception as e:
            is_success = False
            error_msg = f"结果解析异常: {str(e)}"
            
        if not is_success:
            _LOGGER.warning("[Visualizer Agent] Validation failed: %s", error_msg)
            return {
                "chart_result": result,
                "retry_count": retry_count + 1,
                "error_feedback": error_msg
            }
        
        return {"chart_result": result, "error_feedback": ""}
        
    except Exception as e:
        _LOGGER.error("[Visualizer Agent] python_execute failed: %s", e)
        return {
            "chart_result": f"Error: {e}",
            "retry_count": retry_count + 1,
            "error_feedback": str(e)
        }

def viz_format_final_output(state: VisualizerAgentState, config: RunnableConfig) -> dict:
    """格式化最终输出 - 提取 CHART_DATA 并持久化到文件"""
    result = state.get("chart_result", "")
    analysis_id = state.get("analysis_id", "")
    
    # Extract user_id from config
    user_id = "anonymous"
    if config:
        user_id = config.get("configurable", {}).get("user_id", "anonymous")
    
    # 从 python_execute 结果中提取 CHART_DATA
    try:
        result_json = json.loads(result) if isinstance(result, str) else result
        stdout = result_json.get("stdout", "")
        if "CHART_DATA:" in stdout:
            chart_data_str = stdout.split("CHART_DATA:", 1)[1].strip()
            _LOGGER.info("[Visualizer Agent] Extracted chart data: %s", chart_data_str[:100])
            
            # 持久化图表数据到文件
            if analysis_id:
                try:
                    chart_dir = f"/data/workspace/{user_id}/artifacts/data_analysis_{analysis_id}"
                    os.makedirs(chart_dir, exist_ok=True)
                    chart_path = os.path.join(chart_dir, "chart.json")
                    with open(chart_path, "w", encoding="utf-8") as f:
                        f.write(chart_data_str)
                    _LOGGER.info("[Visualizer Agent] Chart saved to: %s", chart_path)
                except Exception as e:
                    _LOGGER.error("[Visualizer Agent] Failed to save chart: %s", e)
            
            return {"messages": [AIMessage(content=f"VISUALIZER_AGENT_COMPLETE: Chart generated")]}
    except:
        pass
        
    return {"messages": [AIMessage(content=f"VISUALIZER_AGENT_COMPLETE: {result}")]}

def check_viz_retry(state: VisualizerAgentState) -> str:
    """检查 Visualizer Agent 是否需要重试"""
    retry_count = state.get("retry_count", 0)
    error_feedback = state.get("error_feedback", "")
    
    if error_feedback and retry_count < 3:
        _LOGGER.info("[Visualizer Agent] Retrying... Attempt %d", retry_count + 1)
        return "retry"
    return "continue"

# 构建 Visualizer Agent Graph
viz_agent_graph = StateGraph(VisualizerAgentState)
viz_agent_graph.add_node("df_profile", viz_step1_df_profile)
viz_agent_graph.add_node("llm_generate", viz_step2_llm_generate_code)
viz_agent_graph.add_node("python_execute", viz_step3_python_execute)
viz_agent_graph.add_node("format_output", viz_format_final_output)

viz_agent_graph.add_edge(START, "df_profile")
viz_agent_graph.add_edge("df_profile", "llm_generate")
viz_agent_graph.add_edge("llm_generate", "python_execute")

viz_agent_graph.add_conditional_edges(
    "python_execute",
    check_viz_retry,
    {
        "retry": "llm_generate",
        "continue": "format_output"
    }
)
viz_agent_graph.add_edge("format_output", END)

visualizer_agent_runnable = viz_agent_graph.compile()

visualizer_agent = CompiledSubAgent(
    name="visualizer_agent",
    description=VISUALIZER_AGENT_DESCRIPTION,
    runnable=visualizer_agent_runnable,
)
