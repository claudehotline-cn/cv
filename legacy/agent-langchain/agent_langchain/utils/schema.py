"""ECharts 图表相关的 Pydantic 模型定义。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


# ============================================================================
# ECharts 基础组件
# ============================================================================

class EChartsTitle(BaseModel):
    """图表标题配置。"""
    text: str = Field(..., description="主标题文本")
    subtext: Optional[str] = Field(None, description="副标题文本")
    left: Optional[str] = Field("center", description="标题位置")


class EChartsTooltip(BaseModel):
    """提示框配置。"""
    trigger: str = Field("axis", description="触发类型：item/axis/none")
    formatter: Optional[str] = Field(None, description="自定义格式化函数")


class EChartsLegend(BaseModel):
    """图例配置。"""
    data: List[str] = Field(default_factory=list, description="图例数据")
    orient: Optional[str] = Field("horizontal", description="布局方向")
    top: Optional[str] = Field(None, description="距容器顶部距离")


class EChartsAxisLabel(BaseModel):
    """轴标签配置。"""
    rotate: Optional[int] = Field(None, description="标签旋转角度")
    formatter: Optional[str] = Field(None, description="格式化函数")


class EChartsAxis(BaseModel):
    """坐标轴配置。"""
    type: str = Field(..., description="坐标轴类型：category/value/time/log")
    name: Optional[str] = Field(None, description="坐标轴名称")
    data: Optional[List[Any]] = Field(None, description="类目数据（category 类型时使用）")
    axisLabel: Optional[EChartsAxisLabel] = Field(None, description="轴标签配置")


class EChartsSeries(BaseModel):
    """系列数据配置。"""
    name: Optional[str] = Field(None, description="系列名称")
    type: str = Field(..., description="图表类型：line/bar/pie/scatter")
    data: List[Any] = Field(default_factory=list, description="系列数据")
    radius: Optional[str] = Field(None, description="饼图半径")
    smooth: Optional[bool] = Field(None, description="是否平滑曲线（line）")
    stack: Optional[str] = Field(None, description="堆叠分组名称")


class EChartsGrid(BaseModel):
    """网格配置。"""
    left: Optional[str] = Field("10%", description="组件离容器左侧的距离")
    right: Optional[str] = Field("10%", description="组件离容器右侧的距离")
    bottom: Optional[str] = Field("15%", description="组件离容器下侧的距离")
    containLabel: Optional[bool] = Field(True, description="是否包含标签")


# ============================================================================
# ECharts Option 主模型
# ============================================================================

class EChartsOption(BaseModel):
    """ECharts 图表配置。"""
    title: Optional[EChartsTitle] = Field(None, description="标题配置")
    tooltip: Optional[EChartsTooltip] = Field(None, description="提示框配置")
    legend: Optional[EChartsLegend] = Field(None, description="图例配置")
    grid: Optional[EChartsGrid] = Field(None, description="网格配置")
    xAxis: Optional[EChartsAxis] = Field(None, description="X 轴配置")
    yAxis: Optional[EChartsAxis] = Field(None, description="Y 轴配置")
    series: List[EChartsSeries] = Field(default_factory=list, description="系列数据")

    class Config:
        extra = "allow"  # 允许额外字段以支持更多 ECharts 配置


# ============================================================================
# 图表生成结果
# ============================================================================

class ChartResult(BaseModel):
    """图表生成结果。"""
    chart_type: str = Field(..., description="图表类型")
    title: str = Field(..., description="图表标题")
    option: EChartsOption = Field(..., description="ECharts 配置")
    data_shape: Dict[str, int] = Field(..., description="数据形状，如 {rows: 10, columns: 3}")


# ============================================================================
# 便捷构建函数
# ============================================================================

def build_line_or_bar_option(
    title: str,
    chart_type: str,
    x_data: List[Any],
    series_data: Dict[str, List[Any]],
) -> EChartsOption:
    """构建折线图或柱状图配置。"""
    return EChartsOption(
        title=EChartsTitle(text=title),
        tooltip=EChartsTooltip(trigger="axis"),
        legend=EChartsLegend(data=list(series_data.keys())),
        grid=EChartsGrid(),
        xAxis=EChartsAxis(type="category", data=x_data),
        yAxis=EChartsAxis(type="value"),
        series=[
            EChartsSeries(name=name, type=chart_type, data=data)
            for name, data in series_data.items()
        ],
    )


def build_pie_option(
    title: str,
    data: List[Dict[str, Any]],
) -> EChartsOption:
    """构建饼图配置。"""
    return EChartsOption(
        title=EChartsTitle(text=title),
        tooltip=EChartsTooltip(trigger="item"),
        series=[
            EChartsSeries(type="pie", radius="50%", data=data)
        ],
    )


def build_scatter_option(
    title: str,
    x_name: str,
    y_name: str,
    data: List[List[Any]],
) -> EChartsOption:
    """构建散点图配置。"""
    return EChartsOption(
        title=EChartsTitle(text=title),
        tooltip=EChartsTooltip(trigger="item"),
        xAxis=EChartsAxis(type="value", name=x_name),
        yAxis=EChartsAxis(type="value", name=y_name),
        series=[
            EChartsSeries(type="scatter", data=data)
        ],
    )


def build_heatmap_option(
    title: str,
    x_data: List[str],
    y_data: List[str],
    data: List[List[Any]],
) -> Dict[str, Any]:
    """构建热力图配置。
    
    Args:
        title: 图表标题
        x_data: X轴分类数据（如月份）
        y_data: Y轴分类数据（如城市）
        data: 热力图数据，格式为 [[x_idx, y_idx, value], ...]
    """
    # 热力图需要更复杂的配置，直接返回字典
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"position": "top"},
        "grid": {"left": "15%", "right": "10%", "bottom": "15%", "top": "10%"},
        "xAxis": {"type": "category", "data": x_data, "splitArea": {"show": True}},
        "yAxis": {"type": "category", "data": y_data, "splitArea": {"show": True}},
        "visualMap": {
            "min": 0,
            "max": 10,
            "calculable": True,
            "orient": "horizontal",
            "left": "center",
            "bottom": "0%",
        },
        "series": [{
            "name": title,
            "type": "heatmap",
            "data": data,
            "label": {"show": True},
            "emphasis": {
                "itemStyle": {"shadowBlur": 10, "shadowColor": "rgba(0, 0, 0, 0.5)"}
            },
        }],
    }

