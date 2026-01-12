from __future__ import annotations

import io
import json
import logging
import ast
import uuid
import os
import pandas as pd
from contextlib import redirect_stdout, redirect_stderr
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool

from ...llm_runtime import build_chat_llm
from ...schemas import PythonResultSchema, ValidationResultSchema
from ...utils.dataframe_store import store_dataframe, get_dataframe
from .visualizer import validate_chart_option
from datetime import datetime, date
from decimal import Decimal

_LOGGER = logging.getLogger("agent_langchain.tools.python")

def _json_default(obj):
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
    if isinstance(obj, pd.Period):
        return str(obj)  # 处理 pd.Period 类型
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    try:
        if hasattr(obj, "item"):  # numpy types
            return obj.item()
    except Exception:
        pass
    return str(obj)

_FORBIDDEN_IMPORTS = {"os", "subprocess", "shutil", "sys", "pathlib", "socket", "requests", "urllib"}
_FORBIDDEN_BUILTINS = {"open", "exec", "eval", "compile"}
_CODE_REVIEW_ENABLED = True


def _create_safe_globals(analysis_id: Optional[str]) -> Dict[str, Any]:
    """创建安全的执行环境，提供 load_dataframe 函数供代码显式加载数据。"""
    import builtins
    safe_builtins = {k: v for k, v in builtins.__dict__.items() if k not in _FORBIDDEN_BUILTINS}
    
    safe_globals = {"__builtins__": safe_builtins, "__name__": "__main__"}
    
    # 导入常用库
    for lib in ["pandas", "numpy", "json", "datetime"]:
        try:
            if lib == "datetime":
                from datetime import datetime, timedelta, date
                safe_globals.update({"datetime": datetime, "timedelta": timedelta, "date": date})
            elif lib == "pandas":
                import pandas as pd
                safe_globals["pd"] = safe_globals["pandas"] = pd
            elif lib == "numpy":
                import numpy as np
                safe_globals["np"] = safe_globals["numpy"] = np
            elif lib == "json":
                import json as json_module
                # 包装 json.dumps 使其自动处理 Period 等特殊类型
                class SafeJson:
                    loads = json_module.loads
                    load = json_module.load
                    @staticmethod
                    def dumps(obj, **kwargs):
                        kwargs.setdefault('default', _json_default)
                        kwargs.setdefault('ensure_ascii', False)
                        return json_module.dumps(obj, **kwargs)
                    @staticmethod
                    def dump(obj, fp, **kwargs):
                        kwargs.setdefault('default', _json_default)
                        kwargs.setdefault('ensure_ascii', False)
                        return json_module.dump(obj, fp, **kwargs)
                safe_globals["json"] = SafeJson
        except ImportError:
            pass
    
    # 提供显式加载函数（不再自动注入 DataFrame）
    if analysis_id:
        from ...utils.dataframe_store import get_dataframe as _get_df, list_dataframes as _list_dfs
        
        def load_dataframe(name: str) -> pd.DataFrame:
            """从工作区加载指定的 DataFrame。
            
            Args:
                name: DataFrame 名称（如 'sql_result', 'excel_data'）
            
            Returns:
                加载的 DataFrame，如果不存在则抛出异常
            """
            df = _get_df(name, analysis_id)
            if df is None:
                available = _list_dfs(analysis_id)
                raise ValueError(f"DataFrame '{name}' 不存在。可用的 DataFrame: {available}")
            
            # 自动将 Period 类型列转换为字符串，避免序列化和操作错误
            for col in df.columns:
                if pd.api.types.is_period_dtype(df[col]):
                    df[col] = df[col].astype(str)
                    _LOGGER.info("Converted Period column '%s' to string", col)
            
            _LOGGER.info("Loaded DataFrame '%s' from file, shape=%s", name, df.shape)
            return df
        
        def list_dataframes() -> list:
            """列出工作区中所有可用的 DataFrame 名称。"""
            return _list_dfs(analysis_id)
        
        safe_globals["load_dataframe"] = load_dataframe
        safe_globals["list_dataframes"] = list_dataframes
            
    return safe_globals


def _review_python_code(code: str) -> Dict[str, Any]:
    """简单语法检查"""
    try:
        ast.parse(code)
        return {"approved": True, "issues": []}
    except SyntaxError as e:
        return {"approved": False, "issues": [str(e)], "suggestion": "修复语法错误"}


def _persist_chart(chart_json_str: str, analysis_id: str) -> str:
    """保存 Chart JSON"""
    if not analysis_id:
        return ""
    try:
        base_dir = f"/data/workspace/artifacts/data_analysis_{analysis_id}/charts"
        os.makedirs(base_dir, exist_ok=True)
        filepath = os.path.join(base_dir, f"chart_{uuid.uuid4().hex[:8]}.json")
        with open(filepath, 'w') as f:
            json.dump(json.loads(chart_json_str), f, ensure_ascii=False, indent=2)
        return filepath
    except Exception as e:
        _LOGGER.error("Failed to persist chart: %s", e)
        return ""


@tool("python_execute")
def python_execute_tool(
    code: str, 
    analysis_id: str
) -> str:
    """在安全沙箱中执行 Python 代码进行数据分析。
    
    Args:
        code: 要执行的 Python 代码
        analysis_id: 分析任务 ID（必填，用于持久化结果和加载已有 DataFrame）
    """
    if not code or not code.strip():
        raise ValueError("代码不能为空。")

    _LOGGER.info("python_execute: analysis_id=%s", analysis_id)
    
    # 打印待执行代码（响应用户需求）
    _LOGGER.info(f"Executing Python code:\n{'-'*40}\n{code}\n{'-'*40}")

    # 安全检查
    code_lower = code.lower()
    for forbidden in _FORBIDDEN_IMPORTS:
        if f"import {forbidden}" in code_lower or f"from {forbidden}" in code_lower:
            raise ValueError(f"禁止导入模块：{forbidden}")

    # 语法检查
    if _CODE_REVIEW_ENABLED:
        review = _review_python_code(code)
        if not review.get("approved"):
            return json.dumps({"success": False, "error": "语法错误", "issues": review.get("issues")}, ensure_ascii=False)

    safe_globals = _create_safe_globals(analysis_id)
    # 🔴 重要：不使用单独的 locals 字典！
    # Python 3 中列表推导式有独立作用域，无法访问 exec() 的 locals。
    # 解决方案：所有变量都存入 globals，确保推导式内部可以访问。
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    result = None

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            tree = ast.parse(code)
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                body_nodes = tree.body[:-1]
                expr_node = tree.body[-1]
                if body_nodes:
                    # 不传 locals，所有变量存入 safe_globals
                    exec(compile(ast.Module(body=body_nodes, type_ignores=[]), "<string>", "exec"), safe_globals)
                result = eval(compile(ast.Expression(body=expr_node.value), "<string>", "eval"), safe_globals)
            else:
                exec(code, safe_globals)
                result = safe_globals.get("result")

        stdout_out = stdout_capture.getvalue()
        stderr_out = stderr_capture.getvalue()
        
        # 打印执行结果到后端日志
        _LOGGER.info(f"Python Execution Result:\n{'='*50}\nSTDOUT:\n{stdout_out}\n{'='*50}")
        if stderr_out:
            _LOGGER.warning(f"STDERR:\n{stderr_out}")

        # 处理图表输出（仅做简单检查，不阻断，不持久化，交由 Agent 处理）
        if stdout_out and "CHART_DATA:" in stdout_out:
            pass

        output_data = {"success": True, "stdout": stdout_out, "stderr": stderr_out}

        # 自动存储 DataFrame 到工作区
        saved_dfs = []
        if analysis_id:
            for k, v in safe_globals.items():
                if isinstance(v, pd.DataFrame) and not k.startswith("_"):
                    path = store_dataframe(k, v, analysis_id)
                    if path:
                        saved_dfs.append(path)
                    if result is None and k in ("df", "result"):
                        result = v
        
        if saved_dfs:
            output_data["saved_dataframes"] = saved_dfs

        # 处理结果
        if result is not None:
            if isinstance(result, pd.DataFrame):
                output_data["result_type"] = "DataFrame"
                # 🔴 将 Period 等不可序列化类型转换为字符串
                safe_df = result.head(20).copy()
                for col in safe_df.columns:
                    if safe_df[col].dtype == 'period[M]' or safe_df[col].dtype.name.startswith('period'):
                        safe_df[col] = safe_df[col].astype(str)
                    elif safe_df[col].dtype == 'object':
                        # 处理 object 列中可能的 Period 对象
                        safe_df[col] = safe_df[col].apply(lambda x: str(x) if isinstance(x, pd.Period) else x)
                output_data["result_preview"] = safe_df.to_dict(orient="records")
                if analysis_id:
                    store_dataframe("result", result, analysis_id)
            else:
                output_data["result_type"] = type(result).__name__
                output_data["result"] = str(result)
        
        return PythonResultSchema(**output_data).model_dump_json(exclude_none=True)

    except Exception as e:
        _LOGGER.error(f"Python Execution FAILED:\n{'='*50}\nError: {e}\n{'='*50}")
        return PythonResultSchema(success=False, error=str(e)).model_dump_json()


@tool("df_profile")
def df_profile_tool(
    df_name: str = "result",
    analysis_id: Optional[str] = None
) -> str:
    """获取 DataFrame 的元数据摘要。
    
    Args:
        df_name: DataFrame 名称
        analysis_id: 分析任务 ID
    """
    df = get_dataframe(df_name, analysis_id) if analysis_id else None
    if df is None:
        return json.dumps({"error": f"DataFrame '{df_name}' 未找到。请确保已执行 SQL 或 Python 生成数据。"})
    
    info = {
        "name": df_name,
        "rows": len(df),
        "columns": list(df.columns),
        "dtypes": {k: str(v) for k, v in df.dtypes.items()},
        "sample": df.head(3).to_dict(orient="records")
    }
    return json.dumps(info, ensure_ascii=False, default=_json_default)
