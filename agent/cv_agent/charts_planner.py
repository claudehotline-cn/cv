from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from pydantic import ValidationError

from .excel.schema import ExcelChartSpec
from .llm_runtime import build_chat_llm, invoke_llm_with_timeout
from .config import get_settings
import json
import logging
import re

_LOGGER = logging.getLogger("cv_agent.charts_planner")


@dataclass
class TablePreview:
    """LLM 图表规划输入的通用表预览结构。"""

    columns: List[str]
    sample_rows: List[List[Any]]


def _build_chart_planning_prompt(
    preview: TablePreview,
    query: str,
    source_kind: str,
    max_charts: int,
) -> str:
    preview_json = json.dumps(
        {
            "columns": preview.columns,
            "sample_rows": preview.sample_rows,
        },
        ensure_ascii=False,
    )

    return (
        f"你是一个数据分析与图表规划助手。下面是一张已经整理好的结果表（来自 {source_kind} 数据源），以及用户的自然语言问题。\n\n"
        "【结果表结构预览】\n"
        f"{preview_json}\n\n"
        "【用户问题】\n"
        f"{query}\n\n"
        f"你的任务：基于这张结果表和用户问题，规划 1~{max_charts} 个最有价值的图表，并输出一个 JSON 对象：\n"
        "{\n"
        '  "charts": [\n'
        "    {\n"
        '      "id": "chart_1",\n'
        '      "title": "图表标题（简短中文）",\n'
        '      "description": "可选简要说明",\n'
        '      "type": "line" | "bar" | "pie" | "area",\n'
        '      "xField": "作为横轴的字段名，必须是 columns 之一",\n'
        '      "xAxisType": "category" | "time" | "value",\n'
        '      "yFields": ["一个或多个纵轴字段名，必须是 columns 之一且通常为数值列"],\n'
        '      "yAxisType": "value" | "log" | "percent"\n'
        "    },\n"
        "    ...\n"
        "  ]\n"
        "}\n\n"
        "要求：\n"
        "1) 只能从 columns 中选择 xField 和 yFields，不要编造不存在的列名；\n"
        "2) 如果存在时间/日期相关列，通常优先用作 xField；数值列用作 yFields；\n"
        f"3) charts 数量不超过 {max_charts}，至少 1 个；按重要性排序；\n"
        "4) 不要在返回中包含 dataset 或真实 rows，由后端注入；\n"
        "5) 只输出 JSON 对象本身，不要添加解释性文字或 Markdown 代码块。"
    )


def plan_chart_specs_with_llm(
    preview: TablePreview,
    query: str,
    source_kind: str = "db",
    max_charts: int = 3,
) -> List[ExcelChartSpec]:
    """使用 LLM 基于通用表预览生成 1~N 个 ExcelChartSpec。

    - preview: 列与样本行；调用方负责控制 sample_rows 数量；
    - query: 用户的问题描述；
    - source_kind: 数据源类型标记（excel/db），仅用于提示词；
    - max_charts: 允许生成的最大图表数。
    """

    settings = get_settings()
    timeout_sec = float(getattr(settings, "request_timeout_sec", 30.0))
    llm = build_chat_llm(task_name=f"{source_kind}_chart_planner")

    prompt = _build_chart_planning_prompt(
        preview=preview,
        query=query,
        source_kind=source_kind,
        max_charts=max_charts,
    )

    def _invoke() -> str:
        _LOGGER.info("charts_planner.llm_invoke.start source_kind=%s", source_kind)
        result = llm.invoke(prompt)  # type: ignore[call-arg]
        text = getattr(result, "content", str(result))
        _LOGGER.info("charts_planner.llm_invoke.done source_kind=%s", source_kind)
        return str(text or "").strip()

    try:
        raw = invoke_llm_with_timeout(
            task_name=f"{source_kind}_chart_planner",
            fn=_invoke,
            timeout_sec=timeout_sec,
        )
    except TimeoutError as exc:
        _LOGGER.error("charts_planner.llm_timeout source_kind=%s timeout_sec=%.1f", source_kind, timeout_sec)
        raise TimeoutError(f"生成图表规划超时（source={source_kind}, >{timeout_sec}s）") from exc

    raw_str = str(raw or "").strip()
    match = re.search(r"\{.*\}", raw_str, flags=re.DOTALL)
    json_text = match.group(0) if match else raw_str

    try:
        data = json.loads(json_text)
    except Exception as exc:
        _LOGGER.error("charts_planner.invalid_json raw=%s error=%s", raw, exc)
        raise RuntimeError("图表规划 LLM 返回的 JSON 无法解析") from exc

    if not isinstance(data, dict) or "charts" not in data:
        _LOGGER.error("charts_planner.invalid_structure data=%s", data)
        raise RuntimeError("图表规划 LLM 返回了无效结构")

    charts = data.get("charts") or []
    if not isinstance(charts, list) or not charts:
        _LOGGER.error("charts_planner.empty_charts data=%s", data)
        raise RuntimeError("图表规划未包含任何图表方案")

    specs: List[ExcelChartSpec] = []
    for idx, item in enumerate(charts, start=1):
        if not isinstance(item, dict):
            _LOGGER.warning("charts_planner.skip_non_dict index=%d item=%s", idx, item)
            continue
        if not item.get("id"):
            item["id"] = f"chart_{idx}"
        if not item.get("title"):
            item["title"] = query.strip() or "数据分析图表"
        # dataset 由调用方注入，这里仅填充占位结构以通过字段校验；
        # 调用方后续会覆盖 dataset 字段为实际数据集。
        if "dataset" not in item:
            item["dataset"] = {
                "columns": preview.columns,
                "rows": preview.sample_rows,
            }
        try:
            spec = ExcelChartSpec.model_validate(item)
        except ValidationError as exc:
            _LOGGER.error("charts_planner.validation_error index=%d item=%s error=%s", idx, item, exc)
            continue
        specs.append(spec)

    if not specs:
        raise RuntimeError("图表规划结果全部无效，无法生成 ChartSpec")

    return specs
