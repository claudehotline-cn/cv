from __future__ import annotations

import logging
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Dict
from langgraph.graph import END, START, StateGraph

from ..config import get_settings
from ..llm_runtime import build_chat_llm, invoke_llm_with_timeout
from ..charts_planner import TablePreview, plan_chart_specs_with_llm
from .analysis import AnalyzedTable, analyze_dataframe_for_chart
from .echarts_builder import build_chart_results_from_spec
from .loader import load_excel_for_session
from .schema import (
    ExcelAgentResponse,
    ExcelAnalysisPlan,
    ExcelAnalysisRequest,
    ExcelChartDataset,
    ExcelChartPlan,
)

_LOGGER = logging.getLogger("cv_agent.excel")

_EXCEL_GRAPH: Any | None = None


def _build_analysis_plan(table_preview: Dict[str, Any], request: ExcelAnalysisRequest) -> ExcelAnalysisPlan:
    """使用 LLM 根据表预览和用户请求生成整体分析计划（可包含多个图表）。"""

    settings = get_settings()
    timeout_sec = float(getattr(settings, "request_timeout_sec", 30.0))

    llm = build_chat_llm(task_name="excel_analysis_plan")

    columns = table_preview.get("columns") or []
    rows = table_preview.get("rows") or []
    sample_rows = rows[: min(5, len(rows))]

    import json

    preview_text = json.dumps(
        {
            "columns": columns,
            "sample_rows": sample_rows,
        },
        ensure_ascii=False,
    )

    chart_hint = request.chart_type_hint or "auto"

    prompt = (
        "你是一个数据分析规划助手。现在有一张来自 Excel 的数据表，以及用户的自然语言需求。\n\n"
        "【表结构预览】\n"
        f"{preview_text}\n\n"
        "【用户问题】\n"
        f"{request.query}\n\n"
        "你的任务：\n"
        "1) 如果用户在问题中已经明确说了“按哪些列统计/分组”（例如：按月份、按地区、按产品或“按月份和地区”），"
        "   请优先按用户说的维度设置 `group_by`：\n"
        "   - 若只提到一个维度（如“按月份统计”），则 group_by 为该列名，例如 \"month\"；\n"
        "   - 如果提到多个维度（如“按月份和地区统计”），在当前 JSON 结构下只能选其中一个，你应选择最核心的那个（例如先选时间维度 month），但必须保证它出现在 columns 中。\n"
        "2) 如果用户没有说“按什么统计/分组”，则由你自行选择一个最合理的维度列作为 group_by（例如时间、地区、产品等），"
        "   如果你认为只做整体统计更合理，可以将 group_by 设为 null。\n"
        "3) 如果用户在问题中点名了指标（例如“销售额、利润、订单数”），且这些列存在于表中，请优先把这些列名填入 `metrics`；"
        "   否则由你根据列名和类型选择最重要的 1-3 个数值列作为 metrics。\n"
        "4) 聚合方式 `agg` 目前只能是 \"sum\" 或 \"count\"：\n"
        "   - 如果用户语气更像“汇总金额/利润/销量”，请使用 \"sum\"；\n"
        "   - 如果用户强调“条数/次数/订单量/数量统计”，你可以选择 \"count\"；\n"
        "   - 若无法判断，默认使用 \"sum\"。\n"
        "5) 图表类型 `chart_type` 只能是 \"line\"、\"bar\"、\"pie\" 或 \"area\"：\n"
        "   - 如果用户问题中明确说了“折线图/柱状图/饼图/面积图/堆叠柱状图”等，请按用户说的类型映射为对应值（折线→line，柱状/堆叠柱状→bar，饼图→pie，面积图→area）；\n"
        f"   - 如果用户没有指定图表类型，你可以根据自己的判断选择一种，并可参考当前前端提示类型：{chart_hint}，但不必须遵守。\n\n"
        "你可以给出 1~3 个图表方案，按重要性排序，每个图表方案描述一个视角（例如：按月份看销售额和利润；按地区看订单数等）。\n"
        "请严格只输出一个 JSON，不要包含任何额外文字，总体结构示例：\n"
        "{\n"
        "  \"charts\": [\n"
        "    {\n"
        "      \"id\": \"chart_1\",\n"
        "      \"title\": \"各月销售额与利润\",\n"
        "      \"description\": \"简要说明该图表展示的重点，可留空\",\n"
        "      \"group_by\": string 或 null,\n"
        "      \"metrics\": [string, ...],\n"
        "      \"agg\": \"sum\" 或 \"count\",\n"
        "      \"chart_type\": \"line\" | \"bar\" | \"pie\" | \"area\" 或 null\n"
        "    },\n"
        "    {\n"
        "      \"id\": \"chart_2\",\n"
        "      \"title\": \"按地区统计销售额\",\n"
        "      \"description\": \"可选的补充说明\",\n"
        "      \"group_by\": string 或 null,\n"
        "      \"metrics\": [string, ...],\n"
        "      \"agg\": \"sum\" 或 \"count\",\n"
        "      \"chart_type\": \"line\" | \"bar\" | \"pie\" | \"area\" 或 null\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "如果你无法合理确定某个字段，也不要缺省，显式填 null 或空数组；若只想返回一个图表方案，则 charts 仅包含一个元素。"
    )

    def _invoke() -> str:
        _LOGGER.info("excel.plan.llm_invoke.start")
        result = llm.invoke(prompt)  # type: ignore[call-arg]
        text = getattr(result, "content", str(result))
        _LOGGER.info("excel.plan.llm_invoke.done")
        return str(text or "").strip()

    import json
    from pydantic import ValidationError

    try:
        raw = invoke_llm_with_timeout(
            task_name="excel_analysis_plan",
            fn=_invoke,
            timeout_sec=timeout_sec,
        )
    except TimeoutError as exc:
        # 保持原有错误信息风格
        _LOGGER.error("excel.plan.llm_timeout timeout_sec=%.1f", timeout_sec)
        raise TimeoutError(f"生成 Excel 分析计划超时（>{timeout_sec}s）") from exc

    try:
        data = json.loads(raw)
    except Exception as exc:
        _LOGGER.error("excel.plan.invalid_json raw=%s error=%s", raw, exc)
        raise RuntimeError("Excel 分析计划 LLM 返回的 JSON 无法解析") from exc

    try:
        plan = ExcelAnalysisPlan.model_validate(data)
    except ValidationError as exc:
        _LOGGER.error("excel.plan.validation_error data=%s error=%s", data, exc)
        raise RuntimeError("Excel 分析计划字段校验失败") from exc

    if not plan.charts:
        _LOGGER.error("excel.plan.empty_charts data=%s", data)
        raise RuntimeError("Excel 分析计划未包含任何图表方案")

    for cp in plan.charts:
        _LOGGER.info(
            "excel.plan.chart_built id=%s title=%s group_by=%s metrics=%s agg=%s chart_type=%s",
            cp.id,
            cp.title,
            cp.group_by,
            cp.metrics,
            cp.agg,
            cp.chart_type,
        )
    return plan


def _build_insight_text(analyzed: AnalyzedTable, request: ExcelAnalysisRequest) -> str:
    """基于聚合表与用户请求，使用 LLM 生成结论；任何失败均抛出异常，由上层返回失败。"""

    settings = get_settings()
    timeout_sec = float(getattr(settings, "request_timeout_sec", 30.0))

    llm = build_chat_llm(task_name="excel_insight")

    # 为避免传输过多数据，仅取前若干行样例
    sample_rows = analyzed.rows[: min(10, len(analyzed.rows))]
    lines = []
    for row in sample_rows:
        line_parts = []
        for idx, col in enumerate(analyzed.columns):
            if idx >= len(row):
                continue
            line_parts.append(f"{col}={row[idx]}")
        lines.append(", ".join(line_parts))
    sample_text = "\n".join(lines)

    prompt = (
        "你是一个数据分析助手，请根据给定的聚合表和用户问题，用简短的中文总结 2-4 句关键结论，"
        "突出整体趋势、峰值/低谷、异常点等。\n\n"
        f"用户问题：{request.query}\n"
        f"分组维度：{analyzed.group_by or '无（整体统计）'}\n"
        f"度量字段：{', '.join(analyzed.metrics) if analyzed.metrics else '计数'}\n"
        "示例数据行（最多 10 行）：\n"
        f"{sample_text}\n\n"
        "请直接输出结论，不要重复列表原始数据。"
    )

    def _invoke() -> str:
        _LOGGER.info("excel.insight.llm_invoke.start")
        result = llm.invoke(prompt)  # type: ignore[call-arg]
        text = getattr(result, "content", str(result))
        _LOGGER.info("excel.insight.llm_invoke.done")
        return str(text or "").strip()

    try:
        return invoke_llm_with_timeout(
            task_name="excel_insight",
            fn=_invoke,
            timeout_sec=timeout_sec,
        )
    except TimeoutError as exc:
        _LOGGER.error("excel.insight.llm_timeout timeout_sec=%.1f", timeout_sec)
        raise TimeoutError(f"生成 Excel 分析结论超时（>{timeout_sec}s）") from exc


def _build_excel_graph() -> Any:
    """构建 Excel 分析 StateGraph。

    状态字典字段约定：
    - request: ExcelAnalysisRequest；
    - df_id: str；
    - used_sheet_name: str；
    - table_preview: dict；
    - analyzed: AnalyzedTable；
    - chart_spec: ExcelChartSpec；
    - response: ExcelAgentResponse。
    """

    graph = StateGraph(dict)

    def load_node(state: Dict[str, Any]) -> Dict[str, Any]:
        request: ExcelAnalysisRequest = state["request"]
        _LOGGER.info(
            "excel.graph.load_node.start session_id=%s file_id=%s sheet_name=%s",
            request.session_id,
            request.file_id,
            request.sheet_name,
        )
        df_id, used_sheet_name, preview = load_excel_for_session(request)
        state["df_id"] = df_id
        state["used_sheet_name"] = used_sheet_name
        state["table_preview"] = preview
        _LOGGER.info(
            "excel.graph.load_node.done df_id=%s used_sheet_name=%s columns=%s",
            df_id,
            used_sheet_name,
            preview.get("columns"),
        )
        return state

    def plan_node(state: Dict[str, Any]) -> Dict[str, Any]:
        request: ExcelAnalysisRequest = state["request"]
        preview: Dict[str, Any] = state["table_preview"]
        _LOGGER.info("excel.graph.plan_node.start")
        plan = _build_analysis_plan(preview, request)
        state["analysis_plan"] = plan
        state["chart_plans"] = plan.charts
        first = plan.charts[0]
        _LOGGER.info(
            "excel.graph.plan_node.done charts=%d first_id=%s first_group_by=%s first_metrics=%s first_agg=%s first_chart_type=%s",
            len(plan.charts),
            first.id,
            first.group_by,
            first.metrics,
            first.agg,
            first.chart_type,
        )
        return state

    def analyze_node(state: Dict[str, Any]) -> Dict[str, Any]:
        df_id: str = state["df_id"]
        chart_plans: list[ExcelChartPlan] = state["chart_plans"]
        _LOGGER.info("excel.graph.analyze_node.start df_id=%s charts=%d", df_id, len(chart_plans))
        analyzed_list: list[AnalyzedTable] = []
        for cp in chart_plans:
            analyzed = analyze_dataframe_for_chart(df_id=df_id, plan=cp)
            analyzed_list.append(analyzed)
        state["analyzed_list"] = analyzed_list
        if analyzed_list:
            state["analyzed"] = analyzed_list[0]
            _LOGGER.info(
                "excel.graph.analyze_node.done df_id=%s first_group_by=%s first_metrics=%s total_charts=%d",
                df_id,
                analyzed_list[0].group_by,
                analyzed_list[0].metrics,
                len(analyzed_list),
            )
        return state

    def chart_spec_node(state: Dict[str, Any]) -> Dict[str, Any]:
        request: ExcelAnalysisRequest = state["request"]
        analyzed_list: list[AnalyzedTable] = state["analyzed_list"]
        chart_plans: list[ExcelChartPlan] = state["chart_plans"]
        _LOGGER.info("excel.graph.chart_spec_node.start charts=%d", len(chart_plans))
        specs = []
        for idx, (cp, analyzed) in enumerate(zip(chart_plans, analyzed_list), start=1):
            chart_id = cp.id or f"excel_chart_{idx}"
            # 使用通用图表规划器基于聚合结果选择 x/y 轴与图表类型；
            preview = TablePreview(
                columns=analyzed.columns,
                sample_rows=analyzed.rows[: min(10, len(analyzed.rows))],
            )
            planner_specs = plan_chart_specs_with_llm(
                preview=preview,
                query=request.query,
                source_kind="excel",
                max_charts=1,
            )
            spec = planner_specs[0]
            spec.id = chart_id
            # 若 LLM 规划未给出标题/描述，则优先使用分析计划中的标题/描述或用户查询。
            title = cp.title or spec.title or request.query
            spec.title = (title or "Excel 数据分析图表").strip()
            description = cp.description or spec.description or None
            spec.description = (description or "").strip() or None
            # 注入聚合结果作为最终数据集。
            spec.dataset = ExcelChartDataset(
                columns=analyzed.columns,
                rows=analyzed.rows,
            )
            specs.append(spec)
            _LOGGER.info(
                "excel.graph.chart_spec_node.chart_done chart_id=%s type=%s x_field=%s y_fields=%s rows=%d",
                spec.id,
                spec.type,
                spec.x_field,
                spec.y_fields,
                len(spec.dataset.rows),
            )
        state["chart_specs"] = specs
        return state

    def build_chart_node(state: Dict[str, Any]) -> Dict[str, Any]:
        specs = state["chart_specs"]
        _LOGGER.info("excel.graph.build_chart_node.start charts=%d", len(specs))
        chart_results = []
        for spec in specs:
            chart_result = build_chart_results_from_spec(spec)
            chart_results.append(chart_result)
            _LOGGER.info(
                "excel.graph.build_chart_node.chart_done chart_id=%s series=%d",
                chart_result.id,
                len(chart_result.option.get("series", [])),
            )
        response = ExcelAgentResponse(
            used_sheet_name=state.get("used_sheet_name"),
            charts=chart_results,
            insight=None,
        )
        state["response"] = response
        return state

    def insight_node(state: Dict[str, Any]) -> Dict[str, Any]:
        request: ExcelAnalysisRequest = state["request"]
        analyzed: AnalyzedTable = state["analyzed"]
        response: ExcelAgentResponse = state["response"]
        _LOGGER.info("excel.graph.insight_node.start")
        insight = _build_insight_text(analyzed=analyzed, request=request)
        state["response"] = ExcelAgentResponse(
            used_sheet_name=response.used_sheet_name,
            charts=response.charts,
            insight=insight,
        )
        _LOGGER.info("excel.graph.insight_node.done")
        return state

    graph.add_node("load_excel", load_node)
    graph.add_node("build_plan", plan_node)
    graph.add_node("analyze_df", analyze_node)
    graph.add_node("build_chart_spec", chart_spec_node)
    graph.add_node("build_chart", build_chart_node)
    graph.add_node("build_insight", insight_node)

    graph.add_edge(START, "load_excel")
    graph.add_edge("load_excel", "build_plan")
    graph.add_edge("build_plan", "analyze_df")
    graph.add_edge("analyze_df", "build_chart_spec")
    graph.add_edge("build_chart_spec", "build_chart")
    graph.add_edge("build_chart", "build_insight")
    graph.add_edge("build_insight", END)

    compiled = graph.compile()
    return compiled


def get_excel_graph() -> Any:
    """返回 Excel 分析 Graph 单例。"""

    global _EXCEL_GRAPH
    if _EXCEL_GRAPH is None:
        _EXCEL_GRAPH = _build_excel_graph()
    return _EXCEL_GRAPH


def invoke_excel_chart_agent(request: ExcelAnalysisRequest) -> ExcelAgentResponse:
    """以一问一答形式执行 Excel 分析 Agent。"""

    graph = get_excel_graph()
    initial_state: Dict[str, Any] = {"request": request}
    try:
        result_state: Dict[str, Any] = graph.invoke(initial_state)  # type: ignore[assignment]
    except Exception as exc:
        _LOGGER.exception("invoke_excel_chart_agent failed: %s", exc)
        raise

    response: ExcelAgentResponse = result_state.get("response")
    if not isinstance(response, ExcelAgentResponse):
        raise ValueError("Excel Agent 未返回有效的响应对象")
    return response
