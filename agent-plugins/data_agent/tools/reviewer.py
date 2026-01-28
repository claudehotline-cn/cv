"""Reviewer Agent 数据验证工具。"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Optional

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

from data_agent.utils.artifacts import get_dataframe

_LOGGER = logging.getLogger("agent_langchain.tools.reviewer")


def _json_default(obj):
    """JSON 序列化默认处理器。"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


@tool("data_validate_result")
def validate_result_tool(
    data_source: str = "result",
    analysis_id: Optional[str] = None,
    config: RunnableConfig = None
) -> str:
    """验证分析结果的有效性。
    
    Args:
        data_source: 数据源名称
        analysis_id: 分析任务 ID
    """
    user_id = "anonymous"
    session_id = "default"
    task_id = None
    if config:
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id", "anonymous")
        session_id = configurable.get("session_id", "default")
        task_id = configurable.get("task_id") or None

    _LOGGER.info("validate_result_tool: data_source=%s, analysis_id=%s, user_id=%s", data_source, analysis_id, user_id)
    
    df = (
        get_dataframe(data_source, analysis_id, user_id, session_id=session_id, task_id=task_id)
        if analysis_id
        else None
    )
    if df is None:
        return json.dumps({"valid": False, "error": f"DataFrame '{data_source}' 不存在"})
    
    warnings = []
    if df.empty:
        warnings.append("DataFrame 为空")
    
    null_cols = df.columns[df.isnull().any()].tolist()
    if null_cols:
        warnings.append(f"以下列包含空值: {null_cols}")
    
    # 🔥 检查数值列的数据类型（Decimal/object 会导致 JSON 序列化失败）
    dtype_issues = []
    for col in df.columns:
        dtype_str = str(df[col].dtype)
        # 检查 object 类型的列是否包含数值（可能是 Decimal）
        if dtype_str == 'object':
            sample = df[col].dropna().head(1)
            if len(sample) > 0:
                sample_val = sample.iloc[0]
                if hasattr(sample_val, '__float__') and not isinstance(sample_val, str):
                    dtype_issues.append(f"{col} (当前类型: {type(sample_val).__name__}, 需转为 float)")
    
    if dtype_issues:
        warnings.append(f"以下数值列需要转换为 float 类型（否则 JSON 序列化失败）: {dtype_issues}")
    
    result = {
        "valid": len(warnings) == 0,
        "data_source": data_source,
        "row_count": len(df),
        "columns": list(df.columns),
        "dtypes": {col: str(df[col].dtype) for col in df.columns},
        "warnings": warnings
    }
    
    _LOGGER.info("validate_result_tool result: valid=%s, warnings=%s", result["valid"], result["warnings"])
    
    return json.dumps(result, ensure_ascii=False, default=_json_default)
