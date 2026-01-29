"""公用工具函数和类型定义。"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def json_default(obj: Any) -> Any:
    """JSON 序列化默认处理器。
    
    处理以下类型：
    - Decimal -> float
    - 其他不可序列化类型 -> str
    """
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def safe_json_dumps(data: Any, **kwargs) -> str:
    """安全的 JSON 序列化，自动处理 Decimal 等特殊类型。
    
    Args:
        data: 要序列化的数据
        **kwargs: 传递给 json.dumps 的其他参数
        
    Returns:
        JSON 字符串
    """
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("default", json_default)
    return json.dumps(data, **kwargs)
