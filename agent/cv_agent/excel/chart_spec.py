from __future__ import annotations

from typing import List, Optional

from .analysis import AnalyzedTable
from .schema import ExcelAnalysisRequest, ExcelChartDataset, ExcelChartSpec


def _infer_chart_type(
    analyzed: AnalyzedTable,
    request: ExcelAnalysisRequest,
    preferred: Optional[str] = None,
) -> str:
    """基于分组字段与 query 推断图表类型。"""

    # 首选来自 LLM 计划的推荐类型（若合法）
    if preferred in ("line", "bar", "pie", "area"):
        return preferred

    query_lower = request.query.lower()

    # 若用户有明确提示，则优先使用
    if request.chart_type_hint is not None:
        return request.chart_type_hint

    # query 中包含“折线/趋势”等关键词 → line
    for kw in ("折线", "趋势", "trend", "变化", "time series"):
        if kw.lower() in query_lower:
            return "line"

    # 若按时间字段分组，默认使用折线图
    if analyzed.group_by is not None:
        group_col_type = analyzed.column_types.get(analyzed.group_by)
        if group_col_type == "time":
            return "line"

    # 默认使用柱状图
    return "bar"


def build_chart_spec_from_analysis(
    analyzed: AnalyzedTable,
    request: ExcelAnalysisRequest,
    chart_id: str = "excel_chart_1",
    preferred_chart_type: Optional[str] = None,
    chart_title: Optional[str] = None,
    chart_description: Optional[str] = None,
) -> ExcelChartSpec:
    """从分析结果表构建单个 ChartSpec。

    当前实现采用简单启发式：
    - 若存在 group_by，则作为 xField，度量列作为 yFields；
    - 若不存在 group_by，则构造“metric/value”结构；
    - 图表类型优先使用 chart_type_hint，否则按 query 与列类型推断。
    """

    columns = analyzed.columns
    rows = analyzed.rows

    if not columns:
        raise ValueError("分析结果表为空，无法生成图表规格")

    x_field: str
    y_fields: List[str]
    dataset_columns: List[str]
    dataset_rows: List[list]

    if analyzed.group_by is not None:
        x_field = analyzed.group_by
        # yFields 取度量列与 group_by 去重后的交集
        y_fields = [c for c in analyzed.metrics if c in columns and c != x_field]
        if not y_fields:
            # 若未找到合适的度量列，则回退到除 group_by 外的数值列
            y_fields = [
                c
                for c in columns
                if c != x_field and analyzed.column_types.get(c) == "number"
            ]
        if not y_fields:
            # 兜底：使用第一个非 group_by 列
            for c in columns:
                if c != x_field:
                    y_fields = [c]
                    break

        dataset_columns = columns
        dataset_rows = rows
    else:
        # 无分组：构造 metric/value 结构，便于作柱状图或条形图
        if not analyzed.metrics:
            # 若连 metrics 都不存在，则直接使用原表结构
            x_field = columns[0]
            y_fields = [c for c in columns[1:] if analyzed.column_types.get(c) == "number"]
            if not y_fields and len(columns) > 1:
                y_fields = [columns[1]]
            dataset_columns = columns
            dataset_rows = rows
        else:
            x_field = "metric"
            y_fields = ["value"]
            dataset_columns = [x_field, "value"]
            dataset_rows = []
            first_row = rows[0] if rows else []
            values_by_col = {
                col: first_row[idx] if idx < len(first_row) else None
                for idx, col in enumerate(columns)
            }
            for metric in analyzed.metrics:
                dataset_rows.append(
                    [metric, values_by_col.get(metric)]
                )

    chart_type = _infer_chart_type(analyzed, request, preferred_chart_type)

    # 轴类型推断
    x_axis_type = "category"
    if analyzed.group_by is not None:
        col_type = analyzed.column_types.get(analyzed.group_by)
        if col_type == "time":
            x_axis_type = "time"
        elif col_type == "number":
            x_axis_type = "value"

    y_axis_type = "value"

    dataset = ExcelChartDataset(columns=dataset_columns, rows=dataset_rows)
    # 若 LLM 已为该图表生成专属标题，则优先使用；否则退回到用户查询语句。
    title = (chart_title or request.query).strip() or "Excel 数据分析图表"
    description = (chart_description or "").strip() or None

    return ExcelChartSpec(
        id=chart_id,
        title=title,
        description=description,
        type=chart_type,  # type: ignore[arg-type]
        xField=x_field,
        xAxisType=x_axis_type,  # type: ignore[arg-type]
        yFields=y_fields,
        yAxisType=y_axis_type,  # type: ignore[arg-type]
        dataset=dataset,
    )
