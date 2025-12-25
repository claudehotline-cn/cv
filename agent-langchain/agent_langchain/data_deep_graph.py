"""统一数据分析 Deep Agent：合并 DB 和 Excel 分析能力，支持 Python 代码执行和自修复。"""

from __future__ import annotations

import io
import json
import logging
import sys
import traceback
from contextlib import redirect_stdout, redirect_stderr
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from langchain.agents import create_agent

from .config import get_settings
from .utils.db_utils import get_sql_database, run_sql_query, load_schema_preview

_LOGGER = logging.getLogger("agent_langchain.data_deep")

# ============================================================================
# DataFrame 内存存储（用于 Python 执行时访问）
# ============================================================================
_CURRENT_DATAFRAMES: Dict[str, Any] = {}


def _store_dataframe(name: str, df: Any) -> None:
    """将 DataFrame 存入内存供 Python 执行使用。"""
    _CURRENT_DATAFRAMES[name] = df


def _get_dataframe(name: str) -> Optional[Any]:
    """获取存储的 DataFrame。"""
    return _CURRENT_DATAFRAMES.get(name)


def _clear_dataframes() -> None:
    """清空所有存储的 DataFrame。"""
    _CURRENT_DATAFRAMES.clear()


# ============================================================================
# 数据库工具
# ============================================================================

@tool("data_db_list_tables")
def db_list_tables_tool() -> Dict[str, Any]:
    """列出当前默认数据库中的候选表及其部分列信息。

    返回：
      {
        "db_name": "...",
        "tables": [
          {"name": "orders", "columns": ["id", "user_id", "amount", ...]}
        ]
      }
    适合在编写 SQL 前先了解有哪些表和大致结构。
    """
    settings = get_settings()
    raw_db_name = getattr(settings, "db_default_name", None)
    if not raw_db_name:
        raise RuntimeError("未配置 db_default_name，无法列出默认数据库的表。")
    db_name = settings.db_extra_databases.get(raw_db_name, raw_db_name)

    schema = load_schema_preview(db_name=db_name, max_tables=16, max_rows=0)
    tables_payload = [{"name": t.name, "columns": t.columns} for t in schema.tables]

    _LOGGER.info("data_deep.db_list_tables done db=%s tables=%d", db_name, len(tables_payload))
    return json.dumps({"db_name": db_name, "tables": tables_payload}, default=str, ensure_ascii=False)


@tool("data_db_table_schema")
def db_table_schema_tool(table: str) -> Dict[str, Any]:
    """查看默认数据库中某个表的列信息与少量样本数据。

    参数：
      - table: 表名，例如 "orders"、"users"。

    返回表结构和最多 5 行样本数据。
    """
    if not table or not table.strip():
        raise ValueError("表名不能为空。")

    settings = get_settings()
    raw_db_name = getattr(settings, "db_default_name", None)
    if not raw_db_name:
        raise RuntimeError("未配置 db_default_name，无法查询表结构。")
    db_name = settings.db_extra_databases.get(raw_db_name, raw_db_name)

    schema = load_schema_preview(db_name=db_name, max_tables=64, max_rows=5)
    target = next((t for t in schema.tables if t.name == table), None)
    if target is None:
        raise ValueError(f"在数据库 {db_name!r} 中未找到表 {table!r}。")

    _LOGGER.info("data_deep.db_table_schema done table=%s columns=%d", table, len(target.columns))
    return json.dumps({
        "db_name": db_name,
        "table": target.name,
        "columns": target.columns,
        "sample_rows": target.sample_rows,
    }, default=str, ensure_ascii=False)


@tool("data_db_run_sql")
def db_run_sql_tool(sql: str) -> Dict[str, Any]:
    """在默认数据库上执行一条只读 SQL，并返回结果表。

    要求：
      - 仅允许 SELECT 或 WITH 开头的查询；
      - 禁止任何写操作。

    参数：
      - sql: 完整的 SQL 查询语句。

    返回 {db_name, sql, columns, rows}，行数限制在 500 以内。
    """
    if not sql or not sql.strip():
        raise ValueError("SQL 不能为空。")

    settings = get_settings()
    raw_db_name = getattr(settings, "db_default_name", None)
    if not raw_db_name:
        raise RuntimeError("未配置 db_default_name，无法执行 SQL。")
    db_name = settings.db_extra_databases.get(raw_db_name, raw_db_name)

    try:
        sql_db = get_sql_database(db_name)
        max_rows = getattr(settings, "excel_max_chart_rows", 500) or 500

        _LOGGER.info("data_deep.db_run_sql start sql=%s", sql[:100])
        result = run_sql_query(db=sql_db, sql=sql, max_rows=max_rows, db_name=db_name)

        # 自动存储为 DataFrame 供后续 Python 分析
        try:
            import pandas as pd
            df = pd.DataFrame(result.rows, columns=result.columns)
            _store_dataframe("sql_result", df)
            _LOGGER.info("data_deep.db_run_sql stored DataFrame sql_result shape=%s", df.shape)
        except Exception as e:
            _LOGGER.warning("data_deep.db_run_sql failed to store DataFrame: %s", e)

        _LOGGER.info("data_deep.db_run_sql done rows=%d columns=%d", len(result.rows), len(result.columns))
        return json.dumps({
            "db_name": db_name,
            "sql": result.sql,
            "columns": list(result.columns),
            "rows": result.rows[:100],  # 只返回前 100 行给 LLM，完整数据在 DataFrame 中
            "total_rows": len(result.rows),
            "note": "完整数据已存储为 'sql_result' DataFrame，可用 python_execute 进一步分析。"
        }, default=str, ensure_ascii=False)
    except Exception as e:
        # 返回错误信息给 LLM 以便它可以修复 SQL
        error_msg = str(e)
        _LOGGER.warning("data_deep.db_run_sql failed: %s", error_msg)
        
        # 识别常见错误并给出修复建议
        suggestion = ""
        if "DATE_TRUNC" in error_msg:
            suggestion = "MySQL 不支持 DATE_TRUNC，请使用 DATE_FORMAT(date, '%Y-%m') 替代。"
        elif "Unknown column" in error_msg:
            suggestion = "列名不存在，请使用 data_db_table_schema 确认正确的列名。"
        elif "Table" in error_msg and "doesn't exist" in error_msg:
            suggestion = "表不存在，请使用 data_db_list_tables 确认正确的表名。"
        elif "syntax" in error_msg.lower():
            suggestion = "SQL 语法错误，请检查 SQL 语句。"

        return json.dumps({
            "success": False,
            "error": error_msg,
            "suggestion": suggestion,
            "note": "SQL 执行失败，请根据错误信息修正 SQL 语句后重试。"
        }, default=str, ensure_ascii=False)


# ============================================================================
# Excel 工具
# ============================================================================

@tool("data_excel_load")
def excel_load_tool(file_path: str, sheet_name: Optional[str] = None) -> Dict[str, Any]:
    """加载 Excel 文件到内存供分析。

    参数：
      - file_path: Excel 文件路径（绝对路径或相对于上传目录）
      - sheet_name: 可选，指定工作表名称，默认加载第一个

    返回文件信息和数据预览。
    """
    if not file_path or not file_path.strip():
        raise ValueError("文件路径不能为空。")

    _LOGGER.info("data_deep.excel_load start file=%s sheet=%s", file_path, sheet_name)

    try:
        import pandas as pd
        
        # 尝试加载 Excel
        if sheet_name:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        else:
            df = pd.read_excel(file_path)

        # 存储 DataFrame
        df_name = "excel_data"
        _store_dataframe(df_name, df)

        preview_rows = df.head(10).to_dict(orient="records")
        
        _LOGGER.info("data_deep.excel_load done shape=%s", df.shape)
        return json.dumps({
            "file_path": file_path,
            "sheet_name": sheet_name or "Sheet1",
            "shape": {"rows": len(df), "columns": len(df.columns)},
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "preview": preview_rows,
            "df_name": df_name,
            "note": f"数据已加载为 '{df_name}' DataFrame，可用 python_execute 进一步分析。"
        }, default=str, ensure_ascii=False)
    except FileNotFoundError:
        raise ValueError(f"文件不存在：{file_path}")
    except Exception as e:
        raise RuntimeError(f"加载 Excel 失败：{e}")


@tool("data_excel_list_sheets")
def excel_list_sheets_tool(file_path: str) -> Dict[str, Any]:
    """列出 Excel 文件中的所有工作表。

    参数：
      - file_path: Excel 文件路径

    返回工作表名称列表。
    """
    if not file_path or not file_path.strip():
        raise ValueError("文件路径不能为空。")

    try:
        import pandas as pd
        xl = pd.ExcelFile(file_path)
        sheets = xl.sheet_names
        _LOGGER.info("data_deep.excel_list_sheets file=%s sheets=%s", file_path, sheets)
        return {"file_path": file_path, "sheets": sheets}
    except Exception as e:
        raise RuntimeError(f"读取 Excel 工作表失败：{e}")


# ============================================================================
# Python 解释器工具
# ============================================================================

# 禁止的导入和内置函数
_FORBIDDEN_IMPORTS = {"os", "subprocess", "shutil", "sys", "pathlib", "socket", "requests", "urllib"}
_FORBIDDEN_BUILTINS = {"open", "exec", "eval", "compile", "__import__"}


def _create_safe_globals() -> Dict[str, Any]:
    """创建安全的执行环境。"""
    import builtins
    
    # 过滤危险的内置函数
    safe_builtins = {k: v for k, v in builtins.__dict__.items() if k not in _FORBIDDEN_BUILTINS}
    
    # 预装常用库
    safe_globals = {
        "__builtins__": safe_builtins,
        "__name__": "__main__",
    }
    
    # 安全导入常用数据分析库
    try:
        import pandas as pd
        safe_globals["pd"] = pd
        safe_globals["pandas"] = pd
    except ImportError:
        pass
    
    try:
        import numpy as np
        safe_globals["np"] = np
        safe_globals["numpy"] = np
    except ImportError:
        pass
    
    try:
        from datetime import datetime, timedelta, date
        safe_globals["datetime"] = datetime
        safe_globals["timedelta"] = timedelta
        safe_globals["date"] = date
    except ImportError:
        pass
    
    try:
        import json
        safe_globals["json"] = json
    except ImportError:
        pass
    
    # 添加存储的 DataFrames
    for name, df in _CURRENT_DATAFRAMES.items():
        safe_globals[name] = df
    
    return safe_globals


@tool("python_execute")
def python_execute_tool(code: str) -> Dict[str, Any]:
    """在安全沙箱中执行 Python 代码进行数据分析。

    参数：
      - code: 要执行的 Python 代码

    可用变量：
      - pd (pandas)
      - np (numpy)
      - datetime, timedelta, date
      - 之前加载的 DataFrame（如 sql_result, excel_data）

    返回值：
      - 如果代码最后一行是表达式，返回其值
      - 如果有 print 输出，返回输出内容
      - 如果有变量 `result`，返回该变量

    安全限制：
      - 禁止文件操作、网络请求、系统命令
      - 执行超时 30 秒
    """
    if not code or not code.strip():
        raise ValueError("代码不能为空。")

    # 检查危险导入
    code_lower = code.lower()
    for forbidden in _FORBIDDEN_IMPORTS:
        if f"import {forbidden}" in code_lower or f"from {forbidden}" in code_lower:
            raise ValueError(f"禁止导入模块：{forbidden}")

    _LOGGER.info("data_deep.python_execute start code_len=%d", len(code))

    # 创建安全执行环境
    safe_globals = _create_safe_globals()
    safe_locals: Dict[str, Any] = {}

    # 捕获输出
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            # 尝试作为表达式执行最后一行
            lines = code.strip().split('\n')
            if len(lines) > 1:
                # 执行除最后一行外的所有代码
                exec('\n'.join(lines[:-1]), safe_globals, safe_locals)
            
            last_line = lines[-1].strip()
            try:
                # 尝试将最后一行作为表达式求值
                result = eval(last_line, {**safe_globals, **safe_locals}, safe_locals)
            except SyntaxError:
                # 如果不是表达式，作为语句执行
                exec(last_line, {**safe_globals, **safe_locals}, safe_locals)
                result = safe_locals.get("result", None)

        stdout_output = stdout_capture.getvalue()
        stderr_output = stderr_capture.getvalue()

        # 处理结果
        output_data: Dict[str, Any] = {
            "success": True,
            "stdout": stdout_output if stdout_output else None,
            "stderr": stderr_output if stderr_output else None,
        }

        # 转换结果为可序列化格式
        if result is not None:
            try:
                import pandas as pd
                if isinstance(result, pd.DataFrame):
                    output_data["result_type"] = "DataFrame"
                    output_data["result_shape"] = {"rows": len(result), "columns": len(result.columns)}
                    output_data["result_columns"] = list(result.columns)
                    output_data["result_preview"] = result.head(20).to_dict(orient="records")
                    # 存储结果 DataFrame
                    _store_dataframe("result", result)
                    output_data["note"] = "结果已存储为 'result' DataFrame"
                elif isinstance(result, pd.Series):
                    output_data["result_type"] = "Series"
                    output_data["result"] = result.head(20).to_dict()
                else:
                    output_data["result_type"] = type(result).__name__
                    output_data["result"] = result if _is_serializable(result) else str(result)
            except Exception:
                output_data["result_type"] = type(result).__name__
                output_data["result"] = str(result)

        _LOGGER.info("data_deep.python_execute success")
        return json.dumps(output_data, default=str, ensure_ascii=False)

    except Exception as e:
        error_msg = traceback.format_exc()
        _LOGGER.warning("data_deep.python_execute failed: %s", e)
        return json.dumps({
            "success": False,
            "error": str(e),
            "traceback": error_msg,
            "suggestion": _get_error_suggestion(str(e)),
        }, default=str, ensure_ascii=False)


def _is_serializable(obj: Any) -> bool:
    """检查对象是否可 JSON 序列化。"""
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


def _get_error_suggestion(error: str) -> str:
    """根据错误类型提供修复建议。"""
    error_lower = error.lower()
    
    if "name" in error_lower and "not defined" in error_lower:
        return "变量未定义。请检查变量名拼写，或确保先加载数据（使用 data_excel_load 或 data_db_run_sql）。"
    elif "keyerror" in error_lower:
        return "列名不存在。请使用 df.columns 查看可用列名。"
    elif "typeerror" in error_lower:
        return "类型错误。请检查数据类型是否正确，可能需要类型转换。"
    elif "valueerror" in error_lower:
        return "值错误。请检查输入数据格式是否正确。"
    elif "indexerror" in error_lower:
        return "索引越界。请检查数据行数/列数。"
    else:
        return "请检查代码语法和逻辑，确保使用了正确的变量名和方法。"


# ============================================================================
# 图表生成工具
# ============================================================================

@tool("data_generate_chart")
def generate_chart_tool(
    chart_type: str,
    title: str,
    data_source: str = "result",
    x_column: Optional[str] = None,
    y_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """根据 DataFrame 生成 ECharts 图表配置（结构化输出）。

    参数：
      - chart_type: 图表类型 (line/bar/pie/scatter)
      - title: 图表标题
      - data_source: DataFrame 名称，默认为 "result"
      - x_column: X 轴列名（折线图/柱状图必需）
      - y_columns: Y 轴列名列表

    返回 Pydantic 验证过的 ECharts option 配置。
    """
    from .utils.schema import (
        ChartResult,
        build_line_or_bar_option,
        build_pie_option,
        build_scatter_option,
    )

    df = _get_dataframe(data_source)
    if df is None:
        # 检查是否有其他可用的 DataFrame
        available = list(_CURRENT_DATAFRAMES.keys())
        if available:
            # 自动使用第一个可用的 DataFrame
            data_source = available[0]
            df = _CURRENT_DATAFRAMES[data_source]
            _LOGGER.info("data_deep.generate_chart auto_fallback to=%s", data_source)
        else:
            raise ValueError(
                f"未找到任何已加载的数据。请先使用 data_db_run_sql 执行 SQL 查询，或使用 data_excel_load 加载 Excel 文件。"
            )

    try:
        import pandas as pd
        if not isinstance(df, pd.DataFrame):
            raise ValueError(f"'{data_source}' 不是有效的 DataFrame。")

        _LOGGER.info("data_deep.generate_chart type=%s title=%s source=%s", chart_type, title, data_source)

        chart_type = chart_type.lower()
        
        # Helper to convert Decimal/datetime/NaN to JSON-serializable types
        def _to_json_serializable(val):
            from decimal import Decimal
            from datetime import datetime, date
            import math
            # Handle NaN and None - convert to 0 for chart compatibility
            if val is None:
                return 0
            if isinstance(val, float) and math.isnan(val):
                return 0
            if isinstance(val, Decimal):
                return float(val)
            if isinstance(val, (datetime, date)):
                return str(val)
            return val

        def _convert_list(lst):
            return [_to_json_serializable(v) for v in lst]
        
        # 验证列名是否存在
        available_columns = list(df.columns)
        if x_column and x_column not in df.columns:
            return json.dumps({
                "success": False,
                "error": f"列 '{x_column}' 不存在于数据中",
                "available_columns": available_columns,
                "suggestion": f"请使用以下列名之一：{available_columns}"
            }, default=str, ensure_ascii=False)
        
        if y_columns:
            missing_cols = [col for col in y_columns if col not in df.columns]
            if missing_cols:
                return json.dumps({
                    "success": False,
                    "error": f"以下列不存在：{missing_cols}",
                    "available_columns": available_columns,
                    "suggestion": f"请使用以下列名：{available_columns}"
                }, default=str, ensure_ascii=False)
        
        if chart_type in ("line", "bar"):
            if not x_column:
                x_column = df.columns[0]
            if not y_columns:
                y_columns = [col for col in df.columns if col != x_column][:5]
            
            x_data = df[x_column].astype(str).tolist()
            series_data = {
                col: _convert_list(df[col].tolist())
                for col in y_columns if col in df.columns
            }
            option = build_line_or_bar_option(title, chart_type, x_data, series_data)

        elif chart_type == "pie":
            name_col = x_column or df.columns[0]
            value_col = y_columns[0] if y_columns else df.columns[1] if len(df.columns) > 1 else df.columns[0]
            
            pie_data = [
                {"name": str(row[name_col]), "value": _to_json_serializable(row[value_col])}
                for _, row in df.head(20).iterrows()
            ]
            option = build_pie_option(title, pie_data)

        elif chart_type == "scatter":
            x_col = x_column or df.columns[0]
            y_col = y_columns[0] if y_columns else df.columns[1] if len(df.columns) > 1 else df.columns[0]
            
            scatter_data = [[_to_json_serializable(row[x_col]), _to_json_serializable(row[y_col])] for _, row in df.iterrows()]
            option = build_scatter_option(title, x_col, y_col, scatter_data)

        else:
            return json.dumps({
                "success": False,
                "error": f"不支持的图表类型：{chart_type}",
                "supported_types": ["line", "bar", "pie", "scatter"],
                "suggestion": "请使用 line, bar, pie 或 scatter 作为 chart_type"
            }, default=str, ensure_ascii=False)

        # 使用 Pydantic 模型验证并序列化
        result = ChartResult(
            chart_type=chart_type,
            title=title,
            option=option,
            data_shape={"rows": len(df), "columns": len(df.columns)},
        )
        
        return result.model_dump()
    
    except KeyError as e:
        available_columns = list(df.columns) if df is not None else []
        return json.dumps({
            "success": False,
            "error": f"列名错误：{e}",
            "available_columns": available_columns,
            "suggestion": f"数据中可用的列名有：{available_columns}。请检查 x_column 和 y_columns 参数。"
        }, default=str, ensure_ascii=False)
    except Exception as e:
        _LOGGER.warning("data_deep.generate_chart failed: %s", e)
        return json.dumps({
            "success": False,
            "error": str(e),
            "suggestion": "请检查参数是否正确，确保数据已正确加载。"
        }, default=str, ensure_ascii=False)


# ============================================================================
# 自审核工具
# ============================================================================

@tool("data_validate_result")
def validate_result_tool(data_source: str = "result") -> Dict[str, Any]:
    """验证分析结果的有效性。

    参数：
      - data_source: 要验证的 DataFrame 名称

    返回验证结果和建议。
    """
    df = _get_dataframe(data_source)
    if df is None:
        return json.dumps({
            "valid": False,
            "error": f"未找到 DataFrame '{data_source}'",
            "suggestion": "请先执行查询或加载数据。"
        }, default=str, ensure_ascii=False)

    import pandas as pd
    if not isinstance(df, pd.DataFrame):
        return json.dumps({
            "valid": False,
            "error": f"'{data_source}' 不是有效的 DataFrame",
            "suggestion": "请检查数据加载步骤。"
        }, default=str, ensure_ascii=False)

    issues = []
    suggestions = []

    # 检查空数据
    if df.empty:
        issues.append("数据为空")
        suggestions.append("请检查查询条件或数据源。")

    # 检查空值
    null_cols = df.columns[df.isnull().any()].tolist()
    if null_cols:
        issues.append(f"以下列包含空值：{null_cols}")
        suggestions.append("可使用 df.dropna() 或 df.fillna() 处理空值。")

    # 检查数据类型
    for col in df.columns:
        if df[col].dtype == "object":
            # 尝试检测数值
            try:
                pd.to_numeric(df[col], errors="raise")
                issues.append(f"列 '{col}' 可能应该是数值类型")
                suggestions.append(f"可使用 df['{col}'] = pd.to_numeric(df['{col}']) 转换。")
            except (ValueError, TypeError):
                pass

    return json.dumps({
        "valid": len(issues) == 0,
        "data_source": data_source,
        "shape": {"rows": len(df), "columns": len(df.columns)},
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "issues": issues if issues else None,
        "suggestions": suggestions if suggestions else None,
    }, default=str, ensure_ascii=False)


# ============================================================================
# 创建统一 Deep Agent
# ============================================================================

def get_data_deep_agent_graph() -> Any:
    """构造并返回统一的数据分析 Deep Agent。

    功能：
      - 数据库查询和分析（DB 工具）
      - Excel 文件加载和分析（Excel 工具）
      - Python 代码执行（数据处理和计算）
      - 图表生成（ECharts）
      - 自审核和建议
    """
    from .llm_runtime import build_chat_llm

    model = build_chat_llm(task_name="data_deep_agent")

    instructions = """
【最重要规则 - 必须遵守】
当用户的请求中包含"图表"、"柱状图"、"折线图"、"饼图"、"可视化"、"chart"等词语时，
你必须在完成数据查询后调用 data_generate_chart 工具生成图表！
这是强制要求，不可用文字描述代替图表！

你是一个统一数据分析 Deep Agent，负责使用多种工具完成用户的数据分析需求。

【可用工具】
1) 数据库工具：
   - data_db_list_tables：列出数据库中的表
   - data_db_table_schema：查看表结构和样本数据
   - data_db_run_sql：执行 SQL 查询（只读）

2) Excel 工具：
   - data_excel_list_sheets：列出 Excel 工作表
   - data_excel_load：加载 Excel 文件

3) Python 分析工具：
   - python_execute：执行 Python 代码（可使用 pandas/numpy）

4) 图表工具：
   - data_generate_chart：生成 ECharts 图表

5) 验证工具：
   - data_validate_result：验证分析结果

【工作流程】
1. 理解数据源：先使用 list_tables/list_sheets 了解可用数据
2. 探索数据：使用 table_schema 或 excel_load 查看数据结构
3. 获取数据：使用 run_sql 或 excel_load 获取数据
4. 分析数据：使用 python_execute 进行复杂计算
5. 验证结果：使用 validate_result 检查数据质量
6. 生成图表：使用 generate_chart 可视化结果

【自修复机制】
- 如果 SQL 执行失败，先用 table_schema 确认表结构，然后修正 SQL
- 如果 Python 执行失败，根据错误信息修正代码
- 如果数据为空，尝试调整查询条件
- 如果验证发现问题，按建议修复

【输出格式】
1. 分析过程：简述你使用的工具和步骤
2. 数据结果：关键统计数据
3. 结论：业务含义和建议
4. 如有图表，会自动展示

【重要】
- 遇到错误时不要放弃，尝试修复
- 多次尝试后仍失败，告知用户具体问题
- 始终使用中文回答
- **当用户提到"图表"、"柱状图"、"折线图"、"饼图"等可视化需求时，你必须调用 data_generate_chart 工具生成图表！这是强制要求。**
- **生成图表前，必须先用 data_db_run_sql 或 data_excel_load 获取数据**

【多系列图表生成 - 重要】
当需要按分组（如城市、类别等）生成多系列图表时：
1. 先执行 SQL 获取包含分组列的原始数据
2. 使用 python_execute 将数据进行 pivot 转换，使每个分组成为单独的列
3. 调用 data_generate_chart 时，将所有分组列名作为 y_columns 参数

这样生成的图表会有多条线/柱（每个分组一条），而不是混合在一起。
"""

    # 清空之前的 DataFrame
    _clear_dataframes()

    return create_agent(
        model=model,
        tools=[
            # 数据库工具
            db_list_tables_tool,
            db_table_schema_tool,
            db_run_sql_tool,
            # Excel 工具
            excel_list_sheets_tool,
            excel_load_tool,
            # Python 执行
            python_execute_tool,
            # 图表生成
            generate_chart_tool,
            # 验证
            validate_result_tool,
        ],
        system_prompt=instructions,
        debug=True,
    )
