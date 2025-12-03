from __future__ import annotations

from typing import Any, Dict, List

from .schema import ExcelChartResult, ExcelChartSpec


def chart_spec_to_echarts_option(spec: ExcelChartSpec) -> Dict[str, Any]:
    """将 ChartSpec 转换为 ECharts option。

    采用官方推荐的 dataset.source 形式构造数据集。
    """

    source: List[list] = [list(spec.dataset.columns)]
    source.extend(list(row) for row in spec.dataset.rows)

    x_axis_config: Dict[str, Any] = {}
    y_axis_config: Dict[str, Any] = {}

    x_axis_type = spec.x_axis_type or "category"
    if x_axis_type == "time":
        x_axis_config["type"] = "time"
    elif x_axis_type == "value":
        x_axis_config["type"] = "value"
    else:
        x_axis_config["type"] = "category"

    if spec.y_axis_type == "log":
        y_axis_config["type"] = "log"
    else:
        y_axis_config["type"] = "value"

    series: List[Dict[str, Any]] = []
    for field in spec.y_fields:
        series.append(
            {
                "type": spec.type,
                "name": field,
                "encode": {
                    "x": spec.x_field,
                    "y": field,
                },
            }
        )

    option: Dict[str, Any] = {
        "title": {"text": spec.title},
        "tooltip": {"trigger": "axis"},
        "legend": {},
        "dataset": {
            "source": source,
        },
        "xAxis": x_axis_config,
        "yAxis": y_axis_config,
        "series": series,
    }

    return option


def build_chart_results_from_spec(spec: ExcelChartSpec) -> ExcelChartResult:
    """根据 ChartSpec 构建单个前端可用的图表结果。"""

    option = chart_spec_to_echarts_option(spec)
    return ExcelChartResult(
        id=spec.id,
        title=spec.title,
        description=spec.description,
        option=option,
    )

