from __future__ import annotations

import logging
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List

import pandas as pd
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from ..config import get_settings
from ..llm_runtime import build_chat_llm, invoke_llm_with_timeout
from ..charts_planner import TablePreview, plan_chart_specs_with_llm
from ..excel.analysis import (
    AnalyzedTable,
    _choose_group_by_column,
    _choose_metric_columns,
    _infer_column_types,
)
from ..excel.echarts_builder import build_chart_results_from_spec
from ..excel.schema import ExcelChartResult, ExcelChartSpec
from .loader import load_schema_preview
from .schema import (
    DbAgentResponse,
    DbAnalysisPlan,
    DbAnalysisRequest,
    DbChartPlan,
    DbSchemaPreview,
)
from .sql_agent import SqlQueryResult, get_sql_database, plan_and_run_sql

_LOGGER = logging.getLogger("cv_agent.db")

_DB_GRAPH: Any | None = None


class _DbAsExcelRequest:
    """最小的“伪 Excel 请求”，仅用于重用图表构建逻辑。

    - 只包含 query 与 chart_type_hint 两个属性；
    - 供 build_chart_spec_from_analysis 使用（鸭子类型即可）。
    """

    def __init__(self, query: str) -> None:
        self.query = query
        self.chart_type_hint = None


def _build_db_analysis_plan(schema: DbSchemaPreview, request: DbAnalysisRequest) -> DbAnalysisPlan:
    """使用 LLM 基于数据库 schema 与用户请求生成整体分析计划。"""

    settings = get_settings()
    timeout_sec = float(getattr(settings, "request_timeout_sec", 30.0))

    llm = build_chat_llm(task_name="db_analysis_plan")

    # 为避免 prompt 过大，仅保留每张表少量样本。
    import json

    tables_preview: List[Dict[str, Any]] = []
    for t in schema.tables:
        tables_preview.append(
            {
                "name": t.name,
                "columns": t.columns,
                "sample_rows": t.sample_rows[:5],
            }
        )

    schema_json = json.dumps(
        {
            "db_name": schema.db_name,
            "tables": tables_preview,
        },
        ensure_ascii=False,
    )

    prompt = (
        "你是一个数据库分析规划助手。现在有一个 MySQL 数据库的部分表结构与样本数据，以及用户的自然语言问题。\n\n"
        "【数据库与表结构预览】\n"
        f"{schema_json}\n\n"
        "【用户问题】\n"
        f"{request.query}\n\n"
        "你的任务：\n"
        "1) 根据用户问题，从上述 tables 中选择 1~3 个最相关的分析视角，每个视角生成一个图表方案（chart）。\n"
        "2) 每个图表方案必须指定：\n"
        "   - table: 使用的主表名，必须严格等于 tables.name 中的某个值；\n"
        "   - group_by: 可为空或为该表中的某个列名，表示按该维度分组（例如时间、地区、产品等）；\n"
        "   - metrics: 该表中需要聚合的 1-3 个数值列名（如金额、销量、数量等）；\n"
        "   - agg: 只能是 \"sum\" 或 \"count\"；\n"
        "   - chart_type: 建议的图表类型，仅能是 \"line\"、\"bar\"、\"pie\" 或 \"area\"；\n"
        "   - title: 简短的中文标题，概括该图表展示的内容；\n"
        "   - description: 可选的简短说明，可为空字符串。\n"
        "3) 若用户问题中明确提到具体的表名/业务对象/字段名或图表类型（如“订单、用户、销售、折线图、饼图”等），请尽量选择对应或语义最接近的表与列，"
        "   并在 chart_type 上遵从用户偏好（例如“折线图”→\"line\"，“柱状图/条形图/堆叠柱状图”→\"bar\"，“饼图”→\"pie\"）。\n"
        "4) 如果用户没有明确说明“按什么维度统计/分组”，你需要自行选择一个最合理的 group_by 列（优先时间、地区、产品等）；若你认为只做整体统计更合理，可以将 group_by 设为 null。\n"
        "5) 如果在某个图表方案中无法找到合适的 metrics（例如没有明显的数值列），可以只使用计数：\n"
        "   - 此时 metrics 可以填写一个你认为重要的列名，agg 通常为 \"count\"。\n"
        "6) 所有 table、group_by、metrics 都必须严格来自提供的 schema 中，禁止虚构表名或列名；如果确实无法找到合适方案，你可以只返回 0 个或 1 个图表。\n\n"
        "请严格只输出一个 JSON，不要包含任何额外文字，总体结构示例：\n"
        "{\n"
        "  \"charts\": [\n"
        "    {\n"
        "      \"id\": \"chart_1\",\n"
        "      \"title\": \"按月份统计订单金额\",\n"
        "      \"description\": \"展示各月订单总金额的变化趋势\",\n"
        "      \"table\": \"orders\",\n"
        "      \"group_by\": \"month\",\n"
        "      \"metrics\": [\"amount\"],\n"
        "      \"agg\": \"sum\",\n"
        "      \"chart_type\": \"line\"\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "如果你无法合理确定某个字段，也不要缺省，显式填 null 或空数组；若暂时只想返回一个图表方案，则 charts 仅包含一个元素。"
    )

    def _invoke() -> str:
        _LOGGER.info("db.plan.llm_invoke.start")
        result = llm.invoke(prompt)  # type: ignore[call-arg]
        text = getattr(result, "content", str(result))
        _LOGGER.info("db.plan.llm_invoke.done")
        return str(text or "").strip()

    try:
        raw = invoke_llm_with_timeout(
            task_name="db_analysis_plan",
            fn=_invoke,
            timeout_sec=timeout_sec,
        )
    except TimeoutError as exc:
        _LOGGER.error("db.plan.llm_timeout timeout_sec=%.1f", timeout_sec)
        raise TimeoutError(f"生成数据库分析计划超时（>{timeout_sec}s）") from exc

    import json

    try:
        data = json.loads(raw)
    except Exception as exc:
        _LOGGER.error("db.plan.invalid_json raw=%s error=%s", raw, exc)
        raise RuntimeError("数据库分析计划 LLM 返回的 JSON 无法解析") from exc

    try:
        plan = DbAnalysisPlan.model_validate(data)
    except ValidationError as exc:
        _LOGGER.error("db.plan.validation_error data=%s error=%s", data, exc)
        raise RuntimeError("数据库分析计划字段校验失败") from exc

    if not plan.charts:
        _LOGGER.error("db.plan.empty_charts data=%s", data)
        raise RuntimeError("数据库分析计划未包含任何图表方案")

    for cp in plan.charts:
        _LOGGER.info(
            "db.plan.chart_built id=%s title=%s table=%s group_by=%s metrics=%s agg=%s chart_type=%s",
            cp.id,
            cp.title,
            cp.table,
            cp.group_by,
            cp.metrics,
            cp.agg,
            cp.chart_type,
        )

    return plan


def _build_db_insight_text(
    tables: List[AnalyzedTable],
    request: DbAnalysisRequest,
) -> str:
    """基于一个或多个聚合表与用户请求，使用 LLM 生成整体结论；失败直接抛错。"""

    settings = get_settings()
    timeout_sec = float(getattr(settings, "request_timeout_sec", 30.0))

    llm = build_chat_llm(task_name="db_insight")

    # 聚合多个图表的关键信息，用于提示词
    lines: List[str] = []
    for idx, analyzed in enumerate(tables, start=1):
        sample_rows = analyzed.rows[: min(5, len(analyzed.rows))]
        header = f"[图表{idx}] 维度={analyzed.group_by or '无（整体统计）'} 度量={', '.join(analyzed.metrics) if analyzed.metrics else '计数'}"
        lines.append(header)
        for row in sample_rows:
            kv_pairs = []
            for col_idx, col_name in enumerate(analyzed.columns):
                if col_idx >= len(row):
                    continue
                kv_pairs.append(f"{col_name}={row[col_idx]}")
            lines.append("  " + ", ".join(kv_pairs))
    sample_text = "\n".join(lines)

    prompt = (
        "你是一个数据库数据分析助手。下面是根据数据库生成的一个或多个聚合结果表，请结合用户的问题，用简短的中文总结 3-5 句关键结论，"
        "强调整体趋势、结构特征、峰值/低谷以及可能的业务含义。\n\n"
        f"用户问题：{request.query}\n\n"
        "聚合结果示例：\n"
        f"{sample_text}\n\n"
        "请直接输出结论段落，不要重复列表原始数据。"
    )

    def _invoke() -> str:
        _LOGGER.info("db.insight.llm_invoke.start")
        result = llm.invoke(prompt)  # type: ignore[call-arg]
        text = getattr(result, "content", str(result))
        _LOGGER.info("db.insight.llm_invoke.done")
        return str(text or "").strip()

    try:
        return invoke_llm_with_timeout(
            task_name="db_insight",
            fn=_invoke,
            timeout_sec=timeout_sec,
        )
    except TimeoutError as exc:
        _LOGGER.error("db.insight.llm_timeout timeout_sec=%.1f", timeout_sec)
        raise TimeoutError(f"生成数据库分析结论超时（>{timeout_sec}s）") from exc


def _build_db_chart_spec_from_result(
    result: SqlQueryResult,
    request: DbAnalysisRequest,
    chart_id: str,
) -> ExcelChartSpec:
    """基于 SQL 查询结果与用户请求，由通用图表规划器生成单个 ChartSpec。"""

    from decimal import Decimal
    import json

    columns = result.columns or []
    rows = result.rows or []

    def _to_jsonable(value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, list):
            return [_to_jsonable(v) for v in value]
        if isinstance(value, tuple):
            return [_to_jsonable(v) for v in value]
        if isinstance(value, dict):
            return {k: _to_jsonable(v) for k, v in value.items()}
        return value

    json_rows = [_to_jsonable(r) for r in rows]
    sample_rows = json_rows[: min(10, len(json_rows))]

    preview = TablePreview(columns=columns, sample_rows=sample_rows)
    specs = plan_chart_specs_with_llm(
        preview=preview,
        query=request.query,
        source_kind="db",
        max_charts=1,
    )
    spec = specs[0]
    spec.id = chart_id
    spec.dataset = spec.dataset.__class__(columns=columns, rows=json_rows)
    return spec


def _build_db_graph() -> Any:
    """构建数据库分析 StateGraph。

    当前版本使用 LangChain SQLDatabase + SQL Query Chain 直接由 LLM 生成 SQL，
    再由后端执行只读查询并构建图表。
    """

    graph = StateGraph(dict)

    def load_schema_node(state: Dict[str, Any]) -> Dict[str, Any]:
        request: DbAnalysisRequest = state["request"]
        settings = get_settings()
        # 先解析请求中的 db_name，若为空则使用默认库名，再通过 db_extra_databases 做别名映射。
        raw_db_name = request.db_name or getattr(settings, "db_default_name", None)
        if not raw_db_name:
            raise RuntimeError("未配置数据库名称（请求未指定且未设置 db_default_name）")
        db_name = settings.db_extra_databases.get(raw_db_name, raw_db_name)

        _LOGGER.info(
            "db.graph.load_schema.start session_id=%s db_name=%s raw_db_name=%s",
            request.session_id,
            db_name,
            raw_db_name,
        )
        schema = load_schema_preview(db_name)
        # 同时构造 SQLDatabase，供后续 SQL Agent 节点复用。
        try:
            sql_db = get_sql_database(db_name)
        except Exception as exc:
            _LOGGER.error("db.graph.load_schema.sql_db_failed db_name=%s error=%s", db_name, exc)
            raise
        state["db_name"] = db_name
        state["schema_preview"] = schema
        state["sql_db"] = sql_db
        _LOGGER.info(
            "db.graph.load_schema.done db_name=%s tables=%d",
            db_name,
            len(schema.tables),
        )
        return state

    def sql_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
        request: DbAnalysisRequest = state["request"]
        db_name: str = state["db_name"]
        sql_db = state.get("sql_db")
        if sql_db is None:
            raise RuntimeError("SQLDatabase 实例缺失，无法执行 SQL Agent 查询")

        # 使用 Excel 的最大行数配置，避免返回数据过大。
        max_rows = getattr(get_settings(), "excel_max_chart_rows", 500)
        if max_rows <= 0:
            max_rows = 500

        _LOGGER.info(
            "db.graph.sql_agent_node.start db_name=%s max_rows=%d",
            db_name,
            max_rows,
        )
        sql_results = plan_and_run_sql(
            request=request,
            db=sql_db,
            db_name=db_name,
            max_rows=max_rows,
        )
        state["sql_results"] = sql_results
        _LOGGER.info(
            "db.graph.sql_agent_node.done db_name=%s results=%d",
            db_name,
            len(sql_results),
        )
        return state

    def analyze_node(state: Dict[str, Any]) -> Dict[str, Any]:
        db_name: str = state["db_name"]
        request: DbAnalysisRequest = state["request"]

        sql_results: List[SqlQueryResult] = state.get("sql_results") or []
        _LOGGER.info(
            "db.graph.analyze_node.start db_name=%s sql_results=%d",
            db_name,
            len(sql_results),
        )

        analyzed_list: List[AnalyzedTable] = []
        if not sql_results:
            raise RuntimeError("SQL Agent 未返回任何查询结果")

        max_rows = getattr(get_settings(), "excel_max_chart_rows", 500)
        if max_rows <= 0:
            max_rows = 500

        for idx, result in enumerate(sql_results, start=1):
            if not result.columns:
                _LOGGER.warning(
                    "db.graph.analyze_node.empty_columns index=%d sql=%s",
                    idx,
                    result.sql,
                )
                continue

            if not result.rows:
                df = pd.DataFrame(columns=result.columns)
            else:
                df = pd.DataFrame(result.rows, columns=result.columns)

            if max_rows > 0 and len(df) > max_rows:
                df = df.head(max_rows)

            column_types = _infer_column_types(df)

            group_by = _choose_group_by_column(
                df=df,
                column_types=column_types,
                query=request.query,
            )
            metrics = _choose_metric_columns(
                df=df,
                column_types=column_types,
                query=request.query,
            )

            analyzed = AnalyzedTable(
                columns=list(df.columns),
                rows=df.to_numpy().tolist(),
                column_types=column_types,
                group_by=group_by,
                metrics=metrics,
            )
            analyzed_list.append(analyzed)

        state["analyzed_list"] = analyzed_list
        if analyzed_list:
            state["analyzed"] = analyzed_list[0]
        _LOGGER.info(
            "db.graph.analyze_node.done charts=%d",
            len(analyzed_list),
        )
        return state

    def chart_spec_node(state: Dict[str, Any]) -> Dict[str, Any]:
        request: DbAnalysisRequest = state["request"]
        sql_results: List[SqlQueryResult] = state.get("sql_results") or []
        _LOGGER.info(
            "db.graph.chart_spec_node.start results=%d",
            len(sql_results),
        )
        if not sql_results:
            raise RuntimeError("SQL Agent 未返回任何查询结果，无法生成图表规格")

        specs: List[ExcelChartSpec] = []
        for idx, result in enumerate(sql_results, start=1):
            chart_id = f"db_chart_{idx}"
            spec = _build_db_chart_spec_from_result(
                result=result,
                request=request,
                chart_id=chart_id,
            )
            specs.append(spec)
            _LOGGER.info(
                "db.graph.chart_spec_node.chart_done chart_id=%s type=%s x_field=%s y_fields=%s rows=%d",
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
        _LOGGER.info(
            "db.graph.build_chart_node.start charts=%d",
            len(specs),
        )
        chart_results: List[ExcelChartResult] = []
        for spec in specs:
            chart_result = build_chart_results_from_spec(spec)
            chart_results.append(chart_result)
            _LOGGER.info(
                "db.graph.build_chart_node.chart_done chart_id=%s series=%d",
                chart_result.id,
                len(chart_result.option.get("series", [])),
            )

        db_name: str = state.get("db_name", "")
        response = DbAgentResponse(
            used_db_name=db_name,
            charts=chart_results,
            insight=None,
        )
        state["response"] = response
        return state

    def insight_node(state: Dict[str, Any]) -> Dict[str, Any]:
        request: DbAnalysisRequest = state["request"]
        analyzed_list: List[AnalyzedTable] = state["analyzed_list"]
        response: DbAgentResponse = state["response"]
        _LOGGER.info("db.graph.insight_node.start charts=%d", len(analyzed_list))
        insight = _build_db_insight_text(tables=analyzed_list, request=request)
        state["response"] = DbAgentResponse(
            used_db_name=response.used_db_name,
            charts=response.charts,
            insight=insight,
        )
        _LOGGER.info("db.graph.insight_node.done")
        return state

    graph.add_node("load_schema", load_schema_node)
    graph.add_node("sql_agent", sql_agent_node)
    graph.add_node("analyze_db", analyze_node)
    graph.add_node("build_chart_spec", chart_spec_node)
    graph.add_node("build_chart", build_chart_node)
    graph.add_node("build_insight", insight_node)

    graph.add_edge(START, "load_schema")
    graph.add_edge("load_schema", "sql_agent")
    graph.add_edge("sql_agent", "analyze_db")
    graph.add_edge("analyze_db", "build_chart_spec")
    graph.add_edge("build_chart_spec", "build_chart")
    graph.add_edge("build_chart", "build_insight")
    graph.add_edge("build_insight", END)

    compiled = graph.compile()
    return compiled


def get_db_graph() -> Any:
    """返回数据库分析 Graph 单例。"""

    global _DB_GRAPH
    if _DB_GRAPH is None:
        _DB_GRAPH = _build_db_graph()
    return _DB_GRAPH


def invoke_db_chart_agent(
    request: DbAnalysisRequest,
    user: Dict[str, Any] | None = None,
) -> DbAgentResponse:
    """以一问一答形式执行数据库分析 Agent。

    - user: 可选的用户上下文，将通过 LangGraph config 透传，便于后续做权限控制与审计。
    """

    graph = get_db_graph()
    initial_state: Dict[str, Any] = {"request": request}

    config: Dict[str, Any] | None = None
    if user is not None:
        config = {
            "configurable": {
                "user_id": user.get("user_id"),
                "role": user.get("role"),
                "tenant": user.get("tenant"),
            }
        }

    try:
        if config is not None:
            result_state: Dict[str, Any] = graph.invoke(initial_state, config=config)  # type: ignore[assignment]
        else:
            result_state = graph.invoke(initial_state)  # type: ignore[assignment]
    except Exception as exc:
        _LOGGER.exception("invoke_db_chart_agent failed: %s", exc)
        raise

    response: DbAgentResponse = result_state.get("response")
    if not isinstance(response, DbAgentResponse):
        raise ValueError("DB Agent 未返回有效的响应对象")
    return response
