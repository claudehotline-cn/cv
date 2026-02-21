from __future__ import annotations

import asyncio
import io
import json
import logging
import ast
import uuid
import os
import sys
from pathlib import Path
import pandas as pd
from contextlib import redirect_stdout, redirect_stderr
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from agent_core.runtime import build_chat_llm
from data_agent.schemas import PythonResultSchema, ValidationResultSchema
from data_agent.utils.artifacts import (
    store_dataframe, 
    get_dataframe, 
    list_dataframes, 
    save_chart, 
    get_backend_from_config
)
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


def _build_python_runner_env() -> Dict[str, str]:
    """Ensure the python_runner subprocess can import in-repo packages."""
    env = os.environ.copy()

    try:
        this_file = Path(__file__).resolve()
        # .../agent-plugins/data_agent/tools/python.py
        agent_plugins_dir = this_file.parents[2]
        repo_root = this_file.parents[3]
        agent_core_dir = repo_root / "agent-core"

        parts: List[str] = [str(agent_plugins_dir), str(agent_core_dir), str(repo_root)]
        existing = env.get("PYTHONPATH", "")
        if existing:
            parts.extend([p for p in existing.split(os.pathsep) if p])

        # De-duplicate while preserving order
        seen = set()
        unique: List[str] = []
        for p in parts:
            if p and p not in seen:
                unique.append(p)
                seen.add(p)

        env["PYTHONPATH"] = os.pathsep.join(unique)
    except Exception:
        # Best effort: if path calculation fails, inherit env.
        pass

    return env


def _create_safe_globals(
    analysis_id: Optional[str],
    user_id: str = "anonymous",
    session_id: str = "default",
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
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
    
    # 提供 load_dataframe / list_dataframes 函数供代码加载数据
    from data_agent.utils.artifacts import get_dataframe as _get_df, list_dataframes as _list_dfs
    
    def load_dataframe(name: str) -> pd.DataFrame:
        """从工作区加载指定的 DataFrame。"""
        if not analysis_id:
            raise ValueError("analysis_id 未传递，无法加载 DataFrame。")
        df = _get_df(name, analysis_id, user_id, session_id=session_id, task_id=task_id)
        if df is None:
            available = _list_dfs(analysis_id, user_id, session_id=session_id, task_id=task_id)
            raise ValueError(f"DataFrame '{name}' 不存在。可用的 DataFrame: {available}")
        
        for col in df.columns:
            if pd.api.types.is_period_dtype(df[col]):
                df[col] = df[col].astype(str)
                _LOGGER.info("Converted Period column '%s' to string", col)
        
        _LOGGER.info("Loaded DataFrame '%s' from file, shape=%s", name, df.shape)
        return df
    
    def list_dataframes() -> list:
        """列出工作区中所有可用的 DataFrame 名称。"""
        if not analysis_id:
            return []
        return _list_dfs(analysis_id, user_id, session_id=session_id, task_id=task_id)
    
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


def _persist_chart(
    chart_json_str: str,
    analysis_id: str,
    user_id: str = "anonymous",
    session_id: str = "default",
    task_id: Optional[str] = None,
) -> str:
    """保存 Chart JSON"""
    return save_chart(
        chart_json_str,
        analysis_id,
        user_id=user_id,
        session_id=session_id,
        task_id=task_id,
    )


def _python_execute_sync(
    code: str, 
    analysis_id: str,
    config: RunnableConfig
) -> str:
    """Synchronous implementation of python execution."""
    if not code or not code.strip():
        raise ValueError("代码不能为空。")

    configurable = config.get("configurable", {})
    user_id = configurable.get("user_id", "anonymous")
    session_id = configurable.get("session_id", "default")
    task_id = configurable.get("task_id") or None
    # 优先从 config 获取 analysis_id，参数作为 fallback
    cfg_analysis_id = configurable.get("analysis_id", "")
    if cfg_analysis_id:
        analysis_id = cfg_analysis_id
    _LOGGER.info("python_execute: analysis_id=%s, user_id=%s", analysis_id, user_id)
    
    # 安全检查
    code_lower = code.lower()
    for forbidden in _FORBIDDEN_IMPORTS:
        if f"import {forbidden}" in code_lower or f"from {forbidden}" in code_lower:
            raise ValueError(f"禁止导入模块：{forbidden}")

    if _CODE_REVIEW_ENABLED:
        review = _review_python_code(code)
        if not review.get("approved"):
            return json.dumps({"success": False, "error": "语法错误", "issues": review.get("issues")}, ensure_ascii=False)

    safe_globals = _create_safe_globals(
        analysis_id,
        user_id=user_id,
        session_id=session_id,
        task_id=task_id,
    )
    
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
                    exec(compile(ast.Module(body=body_nodes, type_ignores=[]), "<string>", "exec"), safe_globals)
                result = eval(compile(ast.Expression(body=expr_node.value), "<string>", "eval"), safe_globals)
            else:
                exec(code, safe_globals)
                result = safe_globals.get("result")

        stdout_out = stdout_capture.getvalue()
        stderr_out = stderr_capture.getvalue()
        
        _LOGGER.info(f"Python Execution Result:\n{'='*50}\nSTDOUT:\n{stdout_out}\n{'='*50}")
        if stderr_out:
            _LOGGER.warning(f"STDERR:\n{stderr_out}")

        output_data = {"success": True, "stdout": stdout_out, "stderr": stderr_out}

        # 自动存储 DataFrame 到工作区
        saved_dfs = []
        if analysis_id:
            for k, v in safe_globals.items():
                if isinstance(v, pd.DataFrame) and not k.startswith("_"):
                    path = store_dataframe(
                        k,
                        v,
                        analysis_id,
                        user_id=user_id,
                        session_id=session_id,
                        task_id=task_id,
                    )
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
                # ... (omitted safe conversion) ...
                safe_df = result.head(20).copy()
                for col in safe_df.columns:
                     if safe_df[col].dtype == 'period[M]' or safe_df[col].dtype.name.startswith('period'):
                         safe_df[col] = safe_df[col].astype(str)
                     elif safe_df[col].dtype == 'object':
                         safe_df[col] = safe_df[col].apply(lambda x: str(x) if isinstance(x, pd.Period) else x)

                output_data["result_preview"] = safe_df.to_dict(orient="records")
                if analysis_id:
                    store_dataframe(
                        "result",
                        result,
                        analysis_id,
                        user_id=user_id,
                        session_id=session_id,
                        task_id=task_id,
                    )
            else:
                output_data["result_type"] = type(result).__name__
                output_data["result"] = str(result)
        
        return PythonResultSchema(**output_data).model_dump_json(exclude_none=True)

    except Exception as e:
        _LOGGER.error(f"Python Execution FAILED:\n{'='*50}\nError: {e}\n{'='*50}")
        return PythonResultSchema(success=False, error=str(e)).model_dump_json()

@tool("python_execute")
async def python_execute_tool(
    code: str, 
    analysis_id: str,
    config: RunnableConfig
) -> str:
    """在安全沙箱中执行 Python 代码进行数据分析。
    
    Args:
        code: 要执行的 Python 代码
        analysis_id: 分析任务 ID（必填，用于持久化结果和加载已有 DataFrame）
    """
    configurable = (config or {}).get("configurable", {})
    user_id = configurable.get("user_id", "anonymous")
    session_id = configurable.get("session_id", "default")
    task_id = configurable.get("task_id") or None

    cfg_analysis_id = configurable.get("analysis_id", "")
    if cfg_analysis_id:
        analysis_id = cfg_analysis_id

    timeout_sec = int(os.environ.get("DATA_AGENT_PY_TIMEOUT_SEC", "20"))

    payload = {
        "code": code,
        "analysis_id": analysis_id,
        "user_id": user_id,
        "session_id": session_id,
        "task_id": task_id,
        "timeout_sec": timeout_sec,
    }

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "data_agent.tools.python_runner",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_build_python_runner_env(),
    )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(input=json.dumps(payload).encode("utf-8")),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return PythonResultSchema(
            success=False,
            error=f"Execution timed out after {timeout_sec}s",
            suggestion="Try reducing data size or simplifying the code.",
        ).model_dump_json(exclude_none=True)

    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")

    if not stdout.strip():
        return PythonResultSchema(
            success=False,
            stdout="",
            stderr=stderr,
            error="python_runner produced no output",
        ).model_dump_json(exclude_none=True)

    # Validate runner output is JSON; if not, wrap it.
    try:
        json.loads(stdout)
    except Exception:
        return PythonResultSchema(
            success=False,
            stdout=stdout,
            stderr=stderr,
            error="python_runner returned invalid JSON",
        ).model_dump_json(exclude_none=True)

    return stdout


@tool("df_profile")
async def df_profile_tool(
    df_name: str = "result",
    analysis_id: Optional[str] = None,
    config: RunnableConfig = None
) -> str:
    """获取 DataFrame 的元数据摘要。
    
    Args:
        df_name: DataFrame 名称
        analysis_id: 分析任务 ID
    """
    return await asyncio.to_thread(_sync_df_profile, df_name, analysis_id, config)


def _sync_df_profile(
    df_name: str,
    analysis_id: Optional[str],
    config: RunnableConfig
) -> str:
    user_id = "anonymous"
    session_id = "default"
    task_id = None
    if config:
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id", "anonymous")
        session_id = configurable.get("session_id", "default")
        task_id = configurable.get("task_id") or None
    
    _LOGGER.info(f"[DEBUG] df_profile_tool: analysis_id={analysis_id}, user_id={user_id}, config_keys={list(config.keys()) if config else 'None'}")

    df = (
        get_dataframe(df_name, analysis_id, user_id, session_id=session_id, task_id=task_id)
        if analysis_id
        else None
    )
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
