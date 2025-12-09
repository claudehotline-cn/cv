from __future__ import annotations

from typing import Any, Dict, List, Set

from .schema import ExcelChartResult, ExcelChartSpec


def chart_spec_to_echarts_option(spec: ExcelChartSpec) -> Dict[str, Any]:
    """将 ChartSpec 转换为 ECharts option。"""

    columns = list(spec.dataset.columns)
    rows = list(spec.dataset.rows)

    # 当 X 轴为时间或日期型类别时，按 X 轴值进行升序排序，保证折线/柱状图的横坐标顺序正确
    sort_idx: int | None = None
    if spec.x_field in columns:
        sort_idx = columns.index(spec.x_field)

    if sort_idx is not None:
        from re import compile as re_compile

        # 简单判断是否类似日期/月份字符串：YYYY-MM 或 YYYY-MM-DD 等
        date_like_pattern = re_compile(r"^\d{4}[-/]\d{2}([-/]\d{2})?$")

        def _is_date_like(value: Any) -> bool:
            if value is None:
                return False
            s = str(value)
            return bool(date_like_pattern.match(s))

        should_sort = False
        if spec.x_axis_type == "time":
            should_sort = True
        elif spec.x_axis_type == "category":
            # 若类别轴上的值看起来全部是日期/月份字符串，也按时间顺序排序
            non_null = [row[sort_idx] for row in rows if sort_idx < len(row) and row[sort_idx] is not None]
            if non_null and all(_is_date_like(v) for v in non_null):
                should_sort = True

        if should_sort:
            rows.sort(
                key=lambda r: "" if sort_idx >= len(r) or r[sort_idx] is None else str(r[sort_idx])
            )

    source: List[list] = [columns]
    source.extend(list(row) for row in rows)

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

    if spec.type == "pie":
        if not spec.y_fields:
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
        if series_dim and series_dim in spec.dataset.columns and spec.y_fields:
            value_field = spec.y_fields[0]
            dim_idx = spec.dataset.columns.index(series_dim)
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
