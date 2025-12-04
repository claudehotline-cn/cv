from __future__ import annotations

from typing import Any, Dict, List, Set

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

    # 将抽象的图表类型映射到 ECharts 的具体 series.type：
    # - line/area: 使用 line 系列，area 通过 areaStyle 开启面积填充
    # - bar: 直接使用 bar 系列
    # - pie: 使用 pie 系列，encode 为 itemName/value
    if spec.type == "pie":
        if not spec.y_fields:
            # 没有明确的度量列时，不生成 series，交由上层错误处理
            return {
                "title": {"text": spec.title},
                "tooltip": {"trigger": "axis"},
                "legend": {},
                "dataset": {"source": source},
                "xAxis": x_axis_config,
                "yAxis": y_axis_config,
                "series": [],
            }
        value_field = spec.y_fields[0]
        series.append(
            {
                "type": "pie",
                "name": value_field,
                "radius": "60%",
                "center": ["50%", "55%"],
                "encode": {
                    "itemName": spec.x_field,
                    "value": value_field,
                },
            }
        )
        dataset_cfg: Any = {"source": source}
    else:
        is_area = spec.type == "area"
        base_type = "line" if spec.type in ("line", "area") else "bar"

        series_dim = getattr(spec, "series_dimension", None)
        # 如果声明了系列维度（例如 city_name），并且该列存在于 dataset.columns 中，
        # 则使用 ECharts dataset transform 按该维度拆分为多条系列。
        if series_dim and series_dim in spec.dataset.columns and spec.y_fields:
            # 仅使用第一个度量列作为 Y 轴，以免一个图表过于复杂。
            value_field = spec.y_fields[0]
            dim_idx = spec.dataset.columns.index(series_dim)
            # 收集有限数量的系列取值（最多 8 个），避免 legend 过长。
            categories: List[Any] = []
            seen: Set[Any] = set()
            for row in spec.dataset.rows:
                if dim_idx >= len(row):
                    continue
                v = row[dim_idx]
                if v in seen or v is None:
                    continue
                seen.add(v)
                categories.append(v)
                if len(categories) >= 8:
                    break

            datasets: List[Dict[str, Any]] = [
                {"source": source},
            ]
            for cat in categories:
                datasets.append(
                    {
                        "fromDatasetIndex": 0,
                        "transform": {
                            "type": "filter",
                            "config": {
                                "dimension": series_dim,
                                "value": cat,
                            },
                        },
                    }
                )
            for idx, cat in enumerate(categories, start=1):
                s: Dict[str, Any] = {
                    "type": base_type,
                    "name": str(cat),
                    "datasetIndex": idx,
                    "encode": {
                        "x": spec.x_field,
                        "y": value_field,
                    },
                }
                if is_area:
                    s["areaStyle"] = {}
                series.append(s)
            dataset_cfg = datasets
        else:
            # 默认行为：一个图中多个度量列，每列一条线/柱。
            for field in spec.y_fields:
                s = {
                    "type": base_type,
                    "name": field,
                    "encode": {
                        "x": spec.x_field,
                        "y": field,
                    },
                }
                if is_area:
                    s["areaStyle"] = {}
                series.append(s)
            dataset_cfg = {"source": source}

    option: Dict[str, Any] = {
        "title": {"text": spec.title},
        "tooltip": {"trigger": "axis"},
        "legend": {},
        "dataset": dataset_cfg,
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
