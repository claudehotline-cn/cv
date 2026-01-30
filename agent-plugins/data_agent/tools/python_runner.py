from __future__ import annotations

import ast
import io
import json
import logging
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional


_LOGGER = logging.getLogger("data_agent.tools.python_runner")


def _json_default(obj: Any) -> Any:
    try:
        import pandas as pd

        if isinstance(obj, (pd.Timestamp, datetime, date)):
            return obj.isoformat()
        if isinstance(obj, pd.Period):
            return str(obj)
    except Exception:
        pass

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    try:
        if hasattr(obj, "item"):
            return obj.item()
    except Exception:
        pass
    return str(obj)


def _apply_resource_limits(timeout_sec: int) -> None:
    try:
        import resource

        cpu = max(1, int(timeout_sec))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))

        mem_mb = int(os.environ.get("DATA_AGENT_PY_MAX_MEM_MB", "2048"))
        mem_bytes = max(128, mem_mb) * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except Exception:
            # RLIMIT_AS may be unsupported depending on platform/container.
            pass
    except Exception:
        # Best-effort; if we can't set limits, continue.
        return


def _install_network_block() -> None:
    try:
        import socket

        def _blocked(*args: Any, **kwargs: Any) -> Any:
            raise PermissionError("Network disabled in python_execute sandbox")

        socket.socket = _blocked  # type: ignore[assignment]
        socket.create_connection = _blocked  # type: ignore[assignment]
        socket.getaddrinfo = _blocked  # type: ignore[assignment]
    except Exception:
        return


def _install_open_sandbox(workspace_root: str) -> None:
    import builtins

    allowed_roots_read = [os.path.realpath(workspace_root)]
    for prefix in (getattr(sys, "prefix", ""), getattr(sys, "base_prefix", ""), getattr(sys, "exec_prefix", "")):
        if prefix:
            allowed_roots_read.append(os.path.realpath(prefix))

    original_open = builtins.open

    def _is_under(path: str, root: str) -> bool:
        if path == root:
            return True
        return path.startswith(root.rstrip(os.sep) + os.sep)

    def safe_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any):
        # Allow file descriptors
        if isinstance(file, int):
            return original_open(file, mode, *args, **kwargs)

        try:
            path = os.path.realpath(os.fspath(file))
        except Exception:
            return original_open(file, mode, *args, **kwargs)

        is_write = any(ch in mode for ch in ("w", "a", "x", "+"))

        allowed = [allowed_roots_read[0]] if is_write else allowed_roots_read

        if not any(_is_under(path, root) for root in allowed):
            raise PermissionError(f"File access denied: {path}")

        return original_open(file, mode, *args, **kwargs)

    builtins.open = safe_open  # type: ignore[assignment]


def _build_safe_builtins() -> Dict[str, Any]:
    import builtins

    allowed = {
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "filter",
        "float",
        "int",
        "isinstance",
        "len",
        "list",
        "map",
        "max",
        "min",
        "pow",
        "print",
        "range",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    }

    safe: Dict[str, Any] = {k: builtins.__dict__[k] for k in allowed if k in builtins.__dict__}

    # Include builtin exceptions so user code can raise/catch them.
    for k, v in builtins.__dict__.items():
        try:
            if isinstance(v, type) and issubclass(v, BaseException):
                safe[k] = v
        except Exception:
            continue

    return safe


def _validate_user_ast(code: str) -> Optional[str]:
    """Return an error message if code is not allowed."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e}"

    forbidden_calls = {"open", "exec", "eval", "compile", "__import__"}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return "Import statements are not allowed. Use preloaded modules (pd, np, json, datetime)."

        if isinstance(node, ast.Attribute) and isinstance(node.attr, str) and node.attr.startswith("__"):
            return "Dunder attribute access is not allowed."

        if isinstance(node, ast.Name) and isinstance(node.id, str) and node.id.startswith("__"):
            return "Dunder names are not allowed."

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in forbidden_calls:
                return f"Calling '{node.func.id}' is not allowed."

    return None


def _execute_code(
    code: str,
    analysis_id: str,
    user_id: str,
    session_id: str,
    task_id: Optional[str],
) -> str:
    from data_agent.schemas import PythonResultSchema
    from data_agent.utils.artifacts import get_dataframe, list_dataframes, store_dataframe

    import pandas as pd
    import numpy as np

    # Apply sandbox hooks after imports (import machinery needs open()).
    from agent_core import WorkspaceBackend
    from agent_core.settings import get_settings

    settings = get_settings()

    # Force temporary files under workspace to avoid touching /tmp.
    try:
        tmp_backend = WorkspaceBackend("data_agent", user_id, session_id, task_id)
        os.makedirs(tmp_backend.tmp_dir, exist_ok=True)
        os.environ["TMPDIR"] = tmp_backend.tmp_dir
        os.environ["TEMP"] = tmp_backend.tmp_dir
        os.environ["TMP"] = tmp_backend.tmp_dir
    except Exception:
        pass

    _install_open_sandbox(settings.workspace_root)
    _install_network_block()

    validation_error = _validate_user_ast(code)
    if validation_error:
        return PythonResultSchema(
            success=False,
            error=validation_error,
            suggestion="Remove unsupported statements (e.g. imports) and retry.",
        ).model_dump_json(exclude_none=True)

    class SafeJson:
        loads = json.loads
        load = json.load

        @staticmethod
        def dumps(obj: Any, **kwargs: Any) -> str:
            kwargs.setdefault("default", _json_default)
            kwargs.setdefault("ensure_ascii", False)
            return json.dumps(obj, **kwargs)

        @staticmethod
        def dump(obj: Any, fp: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("default", _json_default)
            kwargs.setdefault("ensure_ascii", False)
            return json.dump(obj, fp, **kwargs)

    def load_dataframe(name: str) -> pd.DataFrame:
        if not analysis_id:
            raise ValueError("analysis_id 未传递，无法加载 DataFrame。")
        df = get_dataframe(name, analysis_id, user_id, session_id=session_id, task_id=task_id)
        if df is None:
            available = list_dataframes(analysis_id, user_id, session_id=session_id, task_id=task_id)
            raise ValueError(f"DataFrame '{name}' 不存在。可用的 DataFrame: {available}")
        for col in df.columns:
            if pd.api.types.is_period_dtype(df[col]):
                df[col] = df[col].astype(str)
        return df

    def list_dataframes_fn() -> list:
        if not analysis_id:
            return []
        return list_dataframes(analysis_id, user_id, session_id=session_id, task_id=task_id)

    safe_globals: Dict[str, Any] = {
        "__builtins__": _build_safe_builtins(),
        "__name__": "__main__",
        "pd": pd,
        "np": np,
        "json": SafeJson,
        "datetime": datetime,
        "timedelta": timedelta,
        "date": date,
        "load_dataframe": load_dataframe,
        "list_dataframes": list_dataframes_fn,
    }

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    result: Any = None

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            tree = ast.parse(code)
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                body_nodes = tree.body[:-1]
                expr_node = tree.body[-1]
                if body_nodes:
                    exec(
                        compile(ast.Module(body=body_nodes, type_ignores=[]), "<user_code>", "exec"),
                        safe_globals,
                    )
                result = eval(
                    compile(ast.Expression(body=expr_node.value), "<user_code>", "eval"),
                    safe_globals,
                )
            else:
                exec(compile(tree, "<user_code>", "exec"), safe_globals)
                result = safe_globals.get("result")

        stdout_out = stdout_capture.getvalue()
        stderr_out = stderr_capture.getvalue()

        output: Dict[str, Any] = {"success": True, "stdout": stdout_out, "stderr": stderr_out}

        # Auto-persist DataFrames produced by user code.
        saved_dfs = []
        if analysis_id:
            for k, v in safe_globals.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, pd.DataFrame):
                    path = store_dataframe(k, v, analysis_id, user_id=user_id, session_id=session_id, task_id=task_id)
                    if path:
                        saved_dfs.append(path)
                    if result is None and k in ("df", "result"):
                        result = v

        if saved_dfs:
            output["saved_dataframes"] = saved_dfs

        if result is not None:
            if isinstance(result, pd.DataFrame):
                output["result_type"] = "DataFrame"
                output["result_shape"] = str(result.shape)
                output["result_columns"] = list(result.columns)

                safe_df = result.head(20).copy()
                for col in safe_df.columns:
                    if pd.api.types.is_period_dtype(safe_df[col]):
                        safe_df[col] = safe_df[col].astype(str)
                    elif safe_df[col].dtype == "object":
                        safe_df[col] = safe_df[col].apply(lambda x: str(x) if isinstance(x, pd.Period) else x)

                output["result_preview"] = safe_df.to_dict(orient="records")

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
                output["result_type"] = type(result).__name__
                output["result"] = str(result)

        return PythonResultSchema(**output).model_dump_json(exclude_none=True)

    except Exception as e:
        stdout_out = stdout_capture.getvalue()
        stderr_out = stderr_capture.getvalue()
        return PythonResultSchema(
            success=False,
            stdout=stdout_out,
            stderr=stderr_out,
            error=str(e),
        ).model_dump_json(exclude_none=True)


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.stdout.write(
            json.dumps({"success": False, "error": "Invalid JSON input"}, ensure_ascii=False)
        )
        return 0

    code = str(payload.get("code", ""))
    analysis_id = str(payload.get("analysis_id", ""))
    user_id = str(payload.get("user_id", "anonymous"))
    session_id = str(payload.get("session_id", "default"))
    task_id = payload.get("task_id")
    task_id = str(task_id) if task_id else None

    timeout_sec = int(payload.get("timeout_sec") or os.environ.get("DATA_AGENT_PY_TIMEOUT_SEC", "20"))
    _apply_resource_limits(timeout_sec)

    output = _execute_code(code, analysis_id, user_id, session_id, task_id)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
