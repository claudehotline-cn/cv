from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..excel.schema import ExcelChartResult


class DbAnalysisRequest(BaseModel):
    """数据库分析 Agent 请求模型。"""

    session_id: str = Field(description="会话标识，用于复用上下文与审计")
    query: str = Field(description="自然语言分析请求")
    db_name: Optional[str] = Field(
        default=None,
        description="数据库名称；为空则使用默认配置中的库名",
    )


class DbTablePreview(BaseModel):
    """数据库表结构与数据样本预览。"""

    name: str = Field(description="表名")
    columns: List[str] = Field(description="列名列表")
    sample_rows: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="若干行样本数据（用于提供给 LLM）",
    )


class DbSchemaPreview(BaseModel):
    """提供给 LLM 的 schema 预览总结构。"""

    db_name: str = Field(description="当前分析的数据库名")
    tables: List[DbTablePreview] = Field(
        default_factory=list,
        description="候选表列表（已包含少量样本数据）",
    )


class DbChartPlan(BaseModel):
    """由 LLM 决策的单个数据库图表分析计划。"""

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
    table: str = Field(
        description="用于分析的主表名，必须存在于预览的 tables 中",
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


class DbAnalysisPlan(BaseModel):
    """由 LLM 决策的整体数据库分析计划，可包含多个图表。"""

    charts: List[DbChartPlan] = Field(
        default_factory=list,
        description="按重要性排序的图表计划列表",
    )


class DbAgentResponse(BaseModel):
    """数据库分析 Agent 的统一响应结构。"""

    used_db_name: Optional[str] = Field(
        default=None,
        description="实际使用的数据库名称，方便前端展示与调试",
    )
    charts: List[ExcelChartResult] = Field(
        default_factory=list,
        description="生成的图表列表（结构与 Excel Agent 一致）",
    )
    insight: Optional[str] = Field(
        default=None,
        description="整体分析结论或要点摘要",
    )

    sql_traces: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="调试用 SQL 执行摘要列表（语句、行数、列数等），供前端展示数据库工具调用过程",
    )
