"""统一数据分析 Deep Agent (Multi-Agent Version)：基于 deepagents 实现的分层多智能体系统。"""

from __future__ import annotations

import logging
import operator
from typing import Any, TypedDict, Annotated, Sequence

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from deepagents import create_deep_agent, CompiledSubAgent
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
    
    # 3. Python Agent - 使用 StateGraph 创建固化运行图：先 df_profile，再 python_execute
    # =========================================================================
    
    class PythonAgentState(TypedDict):
        """Python Agent 的状态"""
        messages: Annotated[Sequence[BaseMessage], operator.add]
        task_description: str
        analysis_id: str
        df_profile_result: str  # Step 1 的结果
        python_code: str        # LLM 生成的代码
        python_result: str      # Step 2 的结果
    
    def step1_df_profile(state: PythonAgentState) -> dict:
        """Step 1: 调用 df_profile 查看数据结构"""
        _LOGGER.info("[Python Agent Fixed Flow] Step 1: df_profile")
        
        # 从 messages 中提取 analysis_id（格式如 [analysis_id=xxx]）
        import re
        analysis_id = state.get("analysis_id", "")
        task_description = ""
        
        messages = state.get("messages", [])
        for msg in messages:
            content = getattr(msg, "content", "") if hasattr(msg, "content") else str(msg)
            # 尝试匹配 [analysis_id=xxx] 格式
            match = re.search(r'\[analysis_id[=:]?\s*([^\]]+)\]', content, re.IGNORECASE)
            if match:
                analysis_id = match.group(1).strip()
            task_description = content  # 最后一条消息作为任务描述
        
        _LOGGER.info("[Python Agent] Extracted analysis_id=%s", analysis_id)
        
        try:
            result = df_profile_tool.invoke({"df_name": "sql_result", "analysis_id": analysis_id})
            _LOGGER.info("[Python Agent] df_profile result: %s", result[:500] if len(result) > 500 else result)
            return {"df_profile_result": result, "analysis_id": analysis_id, "task_description": task_description}
        except Exception as e:
            _LOGGER.error("[Python Agent] df_profile failed: %s", e)
            return {"df_profile_result": f"Error: {e}", "analysis_id": analysis_id, "task_description": task_description}
    
    def step2_llm_generate_code(state: PythonAgentState) -> dict:
        """Step 2: LLM 根据 df_profile 结果生成 Python 代码"""
        _LOGGER.info("[Python Agent Fixed Flow] Step 2: LLM generate code")
        task = state.get("task_description", "")
        df_info = state.get("df_profile_result", "")
        
        prompt = f"""你是 Python Agent。根据以下信息生成数据处理代码。

【重要】以下函数已在执行环境中预定义，直接使用，**禁止自己定义**：
- `load_dataframe(name)` - 加载指定名称的 DataFrame，例如 `df = load_dataframe('sql_result')`
- `list_dataframes()` - 列出所有可用的 DataFrame 名称

【任务描述】
{task}

【数据结构】（来自 df_profile）
{df_info}

【代码要求】
1. 使用 `df = load_dataframe('sql_result')` 加载数据
2. 根据【数据结构】中的真实列名编写代码，**禁止猜测列名**
3. **数值列转换**：将数值列转为 float 类型 `df['列名'] = df['列名'].astype(float)`
4. **多维数据透视**：如果任务需要按多个维度（如城市+月份）生成图表，使用 `pivot_table` 转换：
   ```python
   # 示例：按城市和月份统计，为 Visualizer 准备数据
   pivot_df = df.pivot_table(index='month', columns='city_name', values='total_amount', aggfunc='sum').reset_index()
   result = pivot_df
   ```
5. 最终结果赋值给 `result` 变量
6. 只输出代码，不要解释"""
        
        response = subagent_llm.invoke([HumanMessage(content=prompt)])
        code = response.content
        # 提取代码块
        if "```python" in code:
            code = code.split("```python")[1].split("```")[0]
        elif "```" in code:
            code = code.split("```")[1].split("```")[0]
        
        _LOGGER.info("[Python Agent] LLM generated code: %s", code[:300])
        return {"python_code": code.strip()}
    
    def step3_python_execute(state: PythonAgentState) -> dict:
        """Step 3: 执行 LLM 生成的 Python 代码"""
        _LOGGER.info("[Python Agent Fixed Flow] Step 3: python_execute")
        code = state.get("python_code", "")
        analysis_id = state.get("analysis_id", "")
        
        if not code:
            return {"python_result": "Error: No code to execute"}
        
        try:
            result = python_execute_tool.invoke({"code": code, "analysis_id": analysis_id})
            _LOGGER.info("[Python Agent] python_execute result: %s", result[:500] if len(result) > 500 else result)
            return {"python_result": result}
        except Exception as e:
            _LOGGER.error("[Python Agent] python_execute failed: %s", e)
            return {"python_result": f"Error: {e}"}
    
    def format_final_output(state: PythonAgentState) -> dict:
        """格式化最终输出为 Agent 消息"""
        result = state.get("python_result", "")
        return {"messages": [AIMessage(content=f"PYTHON_AGENT_COMPLETE: {result}")]}
    
    # 构建固化流程图
    python_agent_graph = StateGraph(PythonAgentState)
    python_agent_graph.add_node("df_profile", step1_df_profile)
    python_agent_graph.add_node("llm_generate", step2_llm_generate_code)
    python_agent_graph.add_node("python_execute", step3_python_execute)
    python_agent_graph.add_node("format_output", format_final_output)
    
    python_agent_graph.add_edge(START, "df_profile")
    python_agent_graph.add_edge("df_profile", "llm_generate")
    python_agent_graph.add_edge("llm_generate", "python_execute")
    python_agent_graph.add_edge("python_execute", "format_output")
    python_agent_graph.add_edge("format_output", END)
    
    python_agent_runnable = python_agent_graph.compile()
    
    python_agent = CompiledSubAgent(
        name="python_agent",
        description=PYTHON_AGENT_DESCRIPTION,
        runnable=python_agent_runnable,
    )
    
    # 4. Reviewer Agent - 使用 StateGraph 创建固化运行图
    # =========================================================================
    
    class ReviewerAgentState(TypedDict):
        """Reviewer Agent 的状态"""
        messages: Annotated[Sequence[BaseMessage], operator.add]
        task_description: str
        analysis_id: str
        validation_result: str
        review_decision: str
    
    def reviewer_step1_validate(state: ReviewerAgentState) -> dict:
        """Step 1: 调用 validate_result_tool 检查数据"""
        _LOGGER.info("[Reviewer Agent Fixed Flow] Step 1: validate_result")
        
        import re
        analysis_id = state.get("analysis_id", "")
        task_description = ""
        
        messages = state.get("messages", [])
        for msg in messages:
            content = getattr(msg, "content", "") if hasattr(msg, "content") else str(msg)
            match = re.search(r'\[analysis_id[=:]?\s*([^\]]+)\]', content, re.IGNORECASE)
            if match:
                analysis_id = match.group(1).strip()
            task_description = content
        
        _LOGGER.info("[Reviewer Agent] Extracted analysis_id=%s", analysis_id)
        
        try:
            result = validate_result_tool.invoke({"data_source": "result", "analysis_id": analysis_id})
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
    
    # 5. Visualizer Agent - 使用 StateGraph 创建固化运行图：先 df_profile，再 python_execute
    # =========================================================================
    
    class VisualizerAgentState(TypedDict):
        """Visualizer Agent 的状态"""
        messages: Annotated[Sequence[BaseMessage], operator.add]
        task_description: str
        analysis_id: str
        df_profile_result: str
        chart_code: str
        chart_result: str
    
    def viz_step1_df_profile(state: VisualizerAgentState) -> dict:
        """Step 1: 调用 df_profile 查看数据结构"""
        _LOGGER.info("[Visualizer Agent Fixed Flow] Step 1: df_profile")
        
        import re
        analysis_id = state.get("analysis_id", "")
        task_description = ""
        
        messages = state.get("messages", [])
        for msg in messages:
            content = getattr(msg, "content", "") if hasattr(msg, "content") else str(msg)
            match = re.search(r'\[analysis_id[=:]?\s*([^\]]+)\]', content, re.IGNORECASE)
            if match:
                analysis_id = match.group(1).strip()
            task_description = content
        
        _LOGGER.info("[Visualizer Agent] Extracted analysis_id=%s", analysis_id)
        
        # 只加载 result（Python Agent 处理后的数据，已转换好类型）
        try:
            result = df_profile_tool.invoke({"df_name": "result", "analysis_id": analysis_id})
            _LOGGER.info("[Visualizer Agent] df_profile(result): %s", result[:500] if len(result) > 500 else result)
            return {"df_profile_result": result, "analysis_id": analysis_id, "task_description": task_description}
        except Exception as e:
            _LOGGER.error("[Visualizer Agent] df_profile(result) failed: %s", e)
            return {"df_profile_result": f'{{"error": "DataFrame result not found: {e}"}}', "analysis_id": analysis_id, "task_description": task_description}
    
    def viz_step2_llm_generate_code(state: VisualizerAgentState) -> dict:
        """Step 2: LLM 根据 df_profile 结果生成 ECharts 代码"""
        _LOGGER.info("[Visualizer Agent Fixed Flow] Step 2: LLM generate chart code")
        task = state.get("task_description", "")
        df_info = state.get("df_profile_result", "")
        
        prompt = f"""你是 Visualizer Agent。根据以下信息生成 ECharts 图表代码。

【重要】以下模块和函数已在执行环境中预定义：
- `json` 模块已导入
- `load_dataframe(name)` - 加载 DataFrame，**必须使用 `load_dataframe('result')`**
- `list_dataframes()` - 列出所有可用的 DataFrame 名称

【任务描述】
{task}

【数据结构】（来自 df_profile）
{df_info}

【代码要求】
1. **必须使用 `df = load_dataframe('result')` 加载数据**（这是 Python Agent 处理后的数据，已转换好类型）
2. 用 Python **字典和列表**构建 chart_option，使用 Python 语法：`True`/`False`（大写！）
3. 使用 `json.dumps()` 将字典转为 JSON 字符串
4. 最后打印 `print("CHART_DATA:" + json.dumps(...))`
5. 只输出代码，不要解释

示例代码模板：
```python
df = load_dataframe('result')
chart_option = {{
    "title": {{"text": "标题"}},
    "xAxis": {{"type": "category", "data": df['月份列'].tolist()}},
    "series": [{{"type": "line", "data": df['数值列'].tolist()}}]
}}
print("CHART_DATA:" + json.dumps({{"success": True, "chart_type": "line", "option": chart_option}}))
```"""
        
        response = subagent_llm.invoke([HumanMessage(content=prompt)])
        code = response.content
        if "```python" in code:
            code = code.split("```python")[1].split("```")[0]
        elif "```" in code:
            code = code.split("```")[1].split("```")[0]
        
        _LOGGER.info("[Visualizer Agent] LLM generated code: %s", code[:300])
        return {"chart_code": code.strip()}
    
    def viz_step3_python_execute(state: VisualizerAgentState) -> dict:
        """Step 3: 执行生成的图表代码"""
        _LOGGER.info("[Visualizer Agent Fixed Flow] Step 3: python_execute")
        code = state.get("chart_code", "")
        analysis_id = state.get("analysis_id", "")
        
        if not code:
            return {"chart_result": "Error: No code to execute"}
        
        try:
            result = python_execute_tool.invoke({"code": code, "analysis_id": analysis_id})
            _LOGGER.info("[Visualizer Agent] python_execute result: %s", result[:500] if len(result) > 500 else result)
            return {"chart_result": result}
        except Exception as e:
            _LOGGER.error("[Visualizer Agent] python_execute failed: %s", e)
            return {"chart_result": f"Error: {e}"}
    
    def viz_format_final_output(state: VisualizerAgentState) -> dict:
        """格式化最终输出 - 提取 CHART_DATA 直接返回给前端"""
        result = state.get("chart_result", "")
        
        # 从 python_execute 结果中提取 CHART_DATA
        import json
        try:
            result_json = json.loads(result) if isinstance(result, str) else result
            stdout = result_json.get("stdout", "")
            if "CHART_DATA:" in stdout:
                # 直接返回 CHART_DATA:... 格式，前端期望这种格式
                chart_data_start = stdout.find("CHART_DATA:")
                chart_data = stdout[chart_data_start:]
                _LOGGER.info("[Visualizer Agent] Returning chart data: %s", chart_data[:200])
                return {"messages": [AIMessage(content=chart_data)]}
        except Exception as e:
            _LOGGER.error("[Visualizer Agent] Failed to extract CHART_DATA: %s", e)
        
        # 回退到原始格式
        return {"messages": [AIMessage(content=f"VISUALIZER_AGENT_COMPLETE: {result}")]}
    
    # 构建 Visualizer 固化流程图
    visualizer_agent_graph = StateGraph(VisualizerAgentState)
    visualizer_agent_graph.add_node("df_profile", viz_step1_df_profile)
    visualizer_agent_graph.add_node("llm_generate", viz_step2_llm_generate_code)
    visualizer_agent_graph.add_node("python_execute", viz_step3_python_execute)
    visualizer_agent_graph.add_node("format_output", viz_format_final_output)
    
    visualizer_agent_graph.add_edge(START, "df_profile")
    visualizer_agent_graph.add_edge("df_profile", "llm_generate")
    visualizer_agent_graph.add_edge("llm_generate", "python_execute")
    visualizer_agent_graph.add_edge("python_execute", "format_output")
    visualizer_agent_graph.add_edge("format_output", END)
    
    visualizer_agent_runnable = visualizer_agent_graph.compile()
    
    visualizer_agent = CompiledSubAgent(
        name="visualizer_agent",
        description=VISUALIZER_AGENT_DESCRIPTION,
        runnable=visualizer_agent_runnable,
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
