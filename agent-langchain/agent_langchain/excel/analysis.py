from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import logging

import pandas as pd

from ..config import get_settings
from .df_store import get_df_store
from .schema import ExcelChartPlan


_LOGGER = logging.getLogger("agent_langchain.excel")


@dataclass
class AnalyzedTable:
    """用于可视化的分析结果表。"""

    columns: List[str]
    rows: List[List[Any]]
    column_types: Dict[str, str]
    group_by: Optional[str]
    metrics: List[str]


_TIME_COLUMN_KEYWORDS = (
    "date",
    "time",
    "datetime",
    "day",
    "week",
    "month",
    "quarter",
    "year",
    "日期",
    "时间",
    "天",
    "周",
    "月",
    "季度",
    "年",
)

_CATEGORY_COLUMN_KEYWORDS = (
    "region",
    "area",
    "city",
    "country",
    "category",
    "type",
    "class",
    "product",
    "item",
    "地区",
    "区域",
    "城市",
    "国家",
    "品类",
    "类别",
    "类型",
    "产品",
    "项目",
)

_METRIC_COLUMN_KEYWORDS = (
    "sale",
    "sales",
    "amount",
    "price",
    "profit",
    "income",
    "revenue",
    "qty",
    "quantity",
    "count",
    "num",
    "数量",
    "金额",
    "价格",
    "利润",
    "收入",
    "营收",
    "次数",
    "数量",
)


def _infer_column_types(df: pd.DataFrame) -> Dict[str, str]:
    """根据 pandas dtype 与列名简单推断列类型。"""

    types: Dict[str, str] = {}
    for name in df.columns:
        series = df[name]
        lower_name = str(name).lower()
        kind = series.dtype.kind

        if kind in ("i", "u", "f"):
            types[name] = "number"
        elif kind == "M":
            types[name] = "time"
        else:
            if any(k in lower_name for k in (kw.lower() for kw in _TIME_COLUMN_KEYWORDS)):
                types[name] = "time"
            elif any(k in lower_name for k in (kw.lower() for kw in _CATEGORY_COLUMN_KEYWORDS)):
                types[name] = "category"
            else:
                types[name] = "category"
    return types


def _choose_group_by_column(
    df: pd.DataFrame,
    column_types: Dict[str, str],
    query: str,
) -> Optional[str]:
    """基于列名/类型和用户 query 选择 group_by 字段。"""

    non_numeric_cols = [c for c in df.columns if column_types.get(c) != "number"]
    if not non_numeric_cols:
        return None

    lowered_query = query.lower()

    for col in non_numeric_cols:
        lower_col = str(col).lower()
        if any(k in lowered_query for k in (kw.lower() for kw in _TIME_COLUMN_KEYWORDS)):
            if any(k in lower_col for k in (kw.lower() for kw in _TIME_COLUMN_KEYWORDS)):
                return col
        if any(k in lowered_query for k in (kw.lower() for kw in _CATEGORY_COLUMN_KEYWORDS)):
            if any(k in lower_col for k in (kw.lower() for kw in _CATEGORY_COLUMN_KEYWORDS)):
                return col

    for col in non_numeric_cols:
        lower_col = str(col).lower()
        if any(k in lower_col for k in (kw.lower() for kw in _TIME_COLUMN_KEYWORDS)):
            return col

    for col in non_numeric_cols:
        lower_col = str(col).lower()
        if any(k in lower_col for k in (kw.lower() for kw in _CATEGORY_COLUMN_KEYWORDS)):
            return col

    return non_numeric_cols[0]


def _choose_metric_columns(
    df: pd.DataFrame,
    column_types: Dict[str, str],
    query: str,
    max_metrics: int = 4,
) -> List[str]:
    """基于列名和 query 选择度量（数值）字段。"""

    numeric_cols = [str(c) for c in df.columns if column_types.get(c) == "number"]
    if not numeric_cols:
        return []

    lowered_query = query.lower()

    scored: List[tuple[int, str]] = []
    for col in numeric_cols:
        lower_col = col.lower()
        score = 0
        if lower_col in lowered_query:
            score += 3
        if any(k in lower_col for k in (kw.lower() for kw in _METRIC_COLUMN_KEYWORDS)):
            score += 2
        if score > 0:
            scored.append((score, col))  # type: ignore[list-item]

    scored_sorted = [c for _, c in sorted(scored, key=lambda x: (-x[0], x[1]))]
    selected: List[str] = []
    for col in scored_sorted:
        if col not in selected:
            selected.append(col)
        if len(selected) >= max_metrics:
            return selected

    for col in numeric_cols:
        if col in selected:
            continue
        selected.append(col)
        if len(selected) >= max_metrics:
            break

    return selected


def analyze_dataframe_for_chart(
    df_id: str,
    plan: ExcelChartPlan,
) -> AnalyzedTable:
    """执行由 LLM 决策的分析计划，将 DataFrame 转为适合作图的聚合表。"""

    settings = get_settings()
    df_store = get_df_store()
    df = df_store.get_df(df_id)
    if df is None:
        raise ValueError(f"DataFrame 不存在或已过期：df_id={df_id}")
    _LOGGER.info(
        "excel.analyze_dataframe_for_chart.start df_id=%s columns=%s rows=%d group_by=%s metrics=%s agg=%s",
        df_id,
        list(df.columns),
        len(df),
        plan.group_by,
        plan.metrics,
        plan.agg,
    )

    column_types = _infer_column_types(df)
    group_by = plan.group_by
    metrics = list(plan.metrics or [])

    if not metrics:
        if group_by is None:
            result_df = pd.DataFrame({"count": [len(df)]})
            column_types = {"count": "number"}
            metrics = ["count"]
        else:
            result_df = (
                df.groupby(group_by, dropna=False)
                .size()
                .reset_index(name="count")
            )
            column_types = {
                group_by: column_types.get(group_by, "category"),
                "count": "number",
            }
            metrics = ["count"]
    else:
        if group_by is None:
            if plan.agg == "count":
                agg_df = df[metrics].count()
            else:
                agg_df = df[metrics].sum(numeric_only=True)
            result_df = agg_df.to_frame().T.reset_index(drop=True)
        else:
            grouped = df.groupby(group_by, dropna=False)[metrics]
            if plan.agg == "count":
                result_df = grouped.count().reset_index()
            else:
                result_df = grouped.sum(numeric_only=True).reset_index()

    max_rows = getattr(settings, "excel_max_chart_rows", 500)
    if max_rows > 0 and len(result_df) > max_rows:
        result_df = result_df.head(max_rows)

    columns = list(result_df.columns)
    rows: List[List[Any]] = result_df.to_numpy().tolist()

    updated_types: Dict[str, str] = {}
    for col in columns:
        if col in column_types:
            updated_types[col] = column_types[col]
        else:
            updated_types[col] = "number"

    analyzed = AnalyzedTable(
        columns=columns,
        rows=rows,
        column_types=updated_types,
        group_by=group_by,
        metrics=metrics,
    )

    _LOGGER.info(
        "excel.analyze_dataframe_for_chart.done df_id=%s group_by=%s metrics=%s out_columns=%s out_rows=%d",
        df_id,
        analyzed.group_by,
        analyzed.metrics,
        analyzed.columns,
        len(analyzed.rows),
    )

    return analyzed

