from __future__ import annotations
import logging
import json
import ast
import re
from typing import Any, Dict, Union, Optional
from langchain_core.tools import tool
from data_agent.schemas import ChartResultSchema, ValidationResultSchema
from agent_core.runtime import build_chat_llm

_LOGGER = logging.getLogger("agent_langchain.tools.visualizer")


def validate_chart_option(chart_data: Dict[str, Any]) -> Dict[str, Any]:
    """使用 Python 逻辑快速验证图表配置。"""
    option = chart_data.get("option", {})
    if not option:
        return {"valid": False, "issues": ["option 为空"], "suggestion": "必须提供 chart_option"}
    
    # Simple semantic checks
    chart_type = chart_data.get("chart_type", "unknown")
    series = option.get("series", [])
    if not series:
        return {"valid": False, "issues": ["series 列表为空"], "suggestion": "请添加 series 数据"}
        
    return {"valid": True, "issues": [], "suggestion": ""}


@tool("data_generate_chart")
def generate_chart_tool(
    option: Union[str, Dict[str, Any]],
    title: str = "数据图表"
) -> str:
    """生成 ECharts 图表。
    """
    _LOGGER.info("generate_chart start title=%s", title)
    
    # 1. Parse option string to dict
    clean_option = str(option).strip()
    if "```" in clean_option:
        clean_option = re.sub(r"```\w*\n?", "", clean_option)
        clean_option = clean_option.replace("```", "").strip()
    if "=" in clean_option[:30]:
        clean_option = clean_option.split("=", 1)[1].strip()

    parsed_option = {}
    try:
        try:
            parsed_option = json.loads(clean_option)
        except:
            try:
                parsed_option = ast.literal_eval(clean_option)
            except:
                start = clean_option.find('{')
                end = clean_option.rfind('}')
                if start != -1 and end != -1:
                    parsed_option = json.loads(clean_option[start:end+1])
                else:
                    raise ValueError("Cannot parse option")
    except Exception as e:
        _LOGGER.warning(f"Option parse failed: {e}")
        parsed_option = {"title": {"text": title}}

    # 2. Return structured output with marker for frontend detection
    _LOGGER.info("Chart option parsed successfully.")
    result_json = ChartResultSchema(
        chart_type=parsed_option.get('series', [{}])[0].get('type', 'unknown'),
        title=title,
        option=parsed_option
    ).model_dump(mode='json')
    
    # Add CHART_DATA: marker for frontend/middleware detection
    # Note: Using json.dumps on result_json ensures it's stringified
    return f"CHART_DATA:{json.dumps(result_json, ensure_ascii=False)}"
