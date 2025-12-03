from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ExcelAnalysisRequest(BaseModel):
    """Excel 分析 Agent 的请求模型。

    - session_id: 用于标识用户会话，便于后续复用 df 缓存；
    - file_id: 由外部文件服务管理的 Excel 文件标识；
    - sheet_name: 可选的 Sheet 名称；为空时由 Agent 自动选择；
    - query: 自然语言分析请求；
    - chart_type_hint: 可选的图表类型提示（例如 line/bar/pie）。
    """

    session_id: str = Field(description="会话标识，用于复用缓存与追踪上下文")
    file_id: str = Field(description="Excel 文件标识，由外部文件服务管理")
    sheet_name: Optional[str] = Field(
        default=None,
        description="可选 Sheet 名称；为空时由 Agent 自动选择",
    )
    query: str = Field(description="自然语言分析请求")
    chart_type_hint: Optional[Literal["line", "bar", "pie", "area"]] = Field(
        default=None,
        description="可选图表类型提示，例如 line/bar/pie/area",
    )


class ExcelChartDataset(BaseModel):
    """ChartSpec 中用于描述数据集的结构。

    - columns: 列名列表；
    - rows: 数据行，每行与 columns 对应。
    """

    columns: List[str] = Field(description="数据列名列表")
    rows: List[List[Any]] = Field(description="数据行列表，每行长度需与 columns 一致")

    @field_validator("rows")
    @classmethod
    def _validate_rows(cls, value: List[List[Any]], info: Any) -> List[List[Any]]:
        columns: List[str] = info.data.get("columns", [])  # type: ignore[assignment]
        col_count = len(columns)
        if col_count == 0:
            return value
        normalized: List[List[Any]] = []
        for row in value:
            # 对于长度不足的行，用 None 填充；过长则截断。
            if len(row) < col_count:
                row = list(row) + [None] * (col_count - len(row))
            elif len(row) > col_count:
                row = list(row[:col_count])
            normalized.append(row)
        return normalized
class ExcelChartPlan(BaseModel):
    """由 LLM 决策的单个图表分析计划。"""

    id: str = Field(
        description="图表计划的唯一标识，例如 chart_1/chart_2",
    )
    title: Optional[str] = Field(
        default=None,
        description="该图表的建议标题，应简短概括图表含义",
    )
    description: Optional[str] = Field(
        default=None,
        description="该图表的简要说明，可为空",
    )
    group_by: Optional[str] = Field(
        default=None,
        description="聚合维度列名，可为空表示整体聚合",
    )
    metrics: List[str] = Field(
        default_factory=list,
        description="度量列名列表，由 LLM 选择",
    )
    agg: Literal["sum", "count"] = Field(
        default="sum",
        description="聚合方式，目前仅支持 sum/count",
    )
    chart_type: Optional[Literal["line", "bar", "pie", "area"]] = Field(
        default=None,
        description="推荐图表类型，可为空，由后续逻辑结合 hint 决定",
    )


class ExcelAnalysisPlan(BaseModel):
    """由 LLM 决策的整体分析计划，可包含多个图表。"""

    charts: List[ExcelChartPlan] = Field(
        default_factory=list,
        description="按重要性排序的图表计划列表",
    )


class ExcelChartSpec(BaseModel):
    """中间层图表规格（ChartSpec）。

    该规格由 LLM 生成，后端再根据该结构构建 ECharts option。
    """

    id: str = Field(description="图表唯一标识，便于前端复用和排查")
    title: str = Field(description="图表标题")
    description: Optional[str] = Field(
        default=None,
        description="图表含义或结论说明，供前端展示",
    )
    type: Literal["line", "bar", "pie", "area"] = Field(
        description="图表类型，例如 line/bar/pie/area"
    )

    x_field: str = Field(
        description="作为 X 轴的字段名，需存在于 dataset.columns 中",
        alias="xField",
    )
    x_axis_type: Literal["category", "time", "value"] = Field(
        default="category",
        description="X 轴类型：category/time/value",
        alias="xAxisType",
    )

    y_fields: List[str] = Field(
        description="作为 Y 轴的字段名列表，需存在于 dataset.columns 中",
        alias="yFields",
    )
    y_axis_type: Literal["value", "log", "percent"] = Field(
        default="value",
        description="Y 轴类型：value/log/percent",
        alias="yAxisType",
    )

    dataset: ExcelChartDataset = Field(description="用于绘图的数据集")

    class Config:
        populate_by_name = True


class ExcelChartResult(BaseModel):
    """后端返回给前端的单个图表结果。"""

    id: str = Field(description="图表唯一标识")
    title: str = Field(description="图表标题")
    description: Optional[str] = Field(
        default=None,
        description="图表含义或结论说明",
    )
    option: Dict[str, Any] = Field(
        description="ECharts option JSON，可直接用于前端渲染"
    )


class ExcelAgentResponse(BaseModel):
    """Excel 分析 Agent 的统一响应结构。"""

    used_sheet_name: Optional[str] = Field(
        default=None,
        description="实际使用的 Sheet 名称（自动选择时便于用户确认）",
    )
    charts: List[ExcelChartResult] = Field(
        default_factory=list,
        description="生成的图表列表",
    )
    insight: Optional[str] = Field(
        default=None,
        description="整体分析结论或要点摘要",
    )
