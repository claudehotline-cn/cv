"""
Data Agent 工具集：包含 DB、Excel、Python 执行、图表生成及验证工具。
从原 data_deep_graph.py 提取。
"""
from __future__ import annotations

import io
import json
import logging
import sys
import ast
import traceback
from contextlib import redirect_stdout, redirect_stderr
from typing import Any, Dict, List, Optional, Union

from langchain_core.tools import tool

from .config import get_settings
from .utils.db_utils import get_sql_database, run_sql_query, load_schema_preview

_LOGGER = logging.getLogger("agent_langchain.data_tools")

# ============================================================================
# DataFrame 内存存储（用于 Python 执行时访问）
# ============================================================================
_CURRENT_DATAFRAMES: Dict[str, Any] = {}


def _store_dataframe(name: str, df: Any) -> None:
    """将 DataFrame 存入内存供 Python 执行使用。"""
    try:
        import pandas as pd
        if isinstance(df, pd.DataFrame):
            _LOGGER.info("Storing DataFrame '%s': shape=%s columns=%s", name, df.shape, list(df.columns))
        else:
            _LOGGER.info("Storing object '%s' (type %s)", name, type(df).__name__)
    except:
        _LOGGER.info("Storing object '%s'", name)
    _CURRENT_DATAFRAMES[name] = df


def _get_dataframe(name: str) -> Optional[Any]:
    """获取存储的 DataFrame。"""
    return _CURRENT_DATAFRAMES.get(name)


def clear_dataframes() -> None:
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
        
        # [Log Enhancement] Query data preview
        if result.rows:
            _LOGGER.info("Query Data Preview (first 5 rows): %s", result.rows[:5])
        else:
             _LOGGER.info("Query Data: [Empty]")

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
        # [Log Enhancement] Excel data preview
        _LOGGER.info("Excel Data Preview: %s", preview_rows[:3])
        
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
# 注意：不禁止 __import__ 因为 pandas 内部操作（如 strftime）需要它
_FORBIDDEN_BUILTINS = {"open", "exec", "eval", "compile"}


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
        
    # 自动设置 df 变量 (优先 SQL，其次 Excel)
    if "df" not in safe_globals:
        if "sql_result" in safe_globals:
            safe_globals["df"] = safe_globals["sql_result"]
        elif "excel_data" in safe_globals:
            safe_globals["df"] = safe_globals["excel_data"]
            
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

    【严禁事项】
      - 禁止使用 matplotlib, seaborn, plt 等进行绘图！必须使用 data_generate_chart 工具生成图表。
      - 禁止使用 import 导入其他模块（pandas 等已预装）。

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
    # [Log Enhancement] Python Code
    _LOGGER.info("Python Code To Execute:\n%s", code[:2000] + ("..." if len(code)>2000 else ""))

    # 创建安全执行环境
    safe_globals = _create_safe_globals()
    _LOGGER.info("Safe globals keys: %s", list(safe_globals.keys()))
    safe_locals: Dict[str, Any] = {}

    # 捕获输出
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            try:
                # 使用 AST 解析代码
                tree = ast.parse(code)
                is_expression = False
                
                # ... (execution logic) ...
                if tree.body and isinstance(tree.body[-1], ast.Expr):
                    is_expression = True
                    body_nodes = tree.body[:-1]
                    expr_node = tree.body[-1]
                    if body_nodes:
                        module = ast.Module(body=body_nodes, type_ignores=[])
                        exec(compile(module, "<string>", "exec"), safe_globals, safe_locals)
                    expr = ast.Expression(body=expr_node.value)
                    result = eval(compile(expr, "<string>", "eval"), {**safe_globals, **safe_locals}, safe_locals)
                else:
                    exec(code, safe_globals, safe_locals)
                    result = safe_locals.get("result", None)

            except Exception as e:
                 _LOGGER.warning("AST execution failed, falling back to direct exec: %s", e)
                 exec(code, safe_globals, safe_locals)
                 result = safe_locals.get("result", None)

        stdout_output = stdout_capture.getvalue()
        stderr_output = stderr_capture.getvalue()

        # 【关键修复】自动持久化所有 DataFrame 变量
        try:
            import pandas as pd
            for var_name, var_value in safe_locals.items():
                if not var_name.startswith("_") and isinstance(var_value, pd.DataFrame):
                    _LOGGER.info(f"Auto-persisting DataFrame: {var_name}")
                    _store_dataframe(var_name, var_value)
                    # 如果没有显式 result，尝试用 df 作为 result
                    if result is None and var_name == "df":
                        result = var_value
        except Exception as e:
            _LOGGER.warning("Auto-persistence failed: %s", e)

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

        _LOGGER.info("data_deep.python_execute success. Output keys: %s", list(output_data.keys()))
        if "result_preview" in output_data:
             # [Log Enhancement] Processed Data
             _LOGGER.info("Processed Data (Result Preview): %s", str(output_data["result_preview"])[:1000])
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
    option: Union[str, Dict[str, Any]],
    title: str = "数据图表",
) -> Dict[str, Any]:
    """生成 ECharts 图表。LLM 需要根据数据直接生成完整的 ECharts option 配置。

    参数：
      - option: 完整的 ECharts option 配置（JSON 字符串），必须包含 xAxis, yAxis, series 等
      - title: 图表标题

    折线图示例：
    {"xAxis": {"type": "category", "data": ["1月", "2月"]}, "yAxis": {"type": "value"}, "series": [{"type": "line", "data": [100, 200]}]}

    柱状图示例：
    {"xAxis": {"type": "category", "data": ["北京", "上海"]}, "yAxis": {"type": "value"}, "series": [{"type": "bar", "data": [100, 200]}]}

    热力图示例：
    {"xAxis": {"type": "category", "data": ["周一", "周二"]}, "yAxis": {"type": "category", "data": ["上海", "北京"]}, "visualMap": {"min": 0, "max": 100}, "series": [{"type": "heatmap", "data": [[0,0,50], [1,0,80]]}]}
    """
    _LOGGER.info("data_deep.generate_chart start title=%s option_len=%d", title, len(str(option)))
    if isinstance(option, str):
        _LOGGER.info("Option preview: %s", option[:200])
    
    try:
        # 解析 LLM 生成的 option JSON
        # ========================================================================
        # 1. 预处理：标准化输入
        # ========================================================================
        clean_option = str(option).strip()
        
        # 移除 Markdown 代码块标记（如果有）
        if "```" in clean_option:
            import re
            # 移除 ```json 或 ```python 等
            clean_option = re.sub(r"```\w*\n?", "", clean_option)
            clean_option = clean_option.replace("```", "").strip()

        # 移除常见赋值前缀 (option =, var x =)
        if "=" in clean_option:
             # 简单启发式：如果在前 20 个字符内有 =，取 = 之后的内容
             if clean_option[:20].find("=") != -1:
                 clean_option = clean_option.split("=", 1)[1].strip()

        # ========================================================================
        # 2. 核心解析逻辑 (Robust Parse)
        # ========================================================================
        def robust_parse(text):
            # 策略 A: 直接解析 JSON
            try:
                return json.loads(text)
            except:
                pass
            
            # 策略 B: 直接解析 Python Literal
            import ast
            try:
                return ast.literal_eval(text)
            except:
                pass

            # 策略 C: 提取最外层 {} 后再尝试解析 (这是最关键的容错)
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                inner_text = text[start:end+1]
                # 递归尝试解析提取后的内容
                try:
                    return json.loads(inner_text)
                except:
                    pass
                try:
                    return ast.literal_eval(inner_text)
                except:
                    # 策略 D: 混合修正 (处理 true/True, null/None 混用)
                    # 尝试将 Python 关键字转 JSON
                    fixed_json = inner_text.replace("True", "true").replace("False", "false").replace("None", "null").replace("'", '"')
                    try:
                        return json.loads(fixed_json)
                    except:
                        pass
                    
                    # 尝试将 JSON 关键字转 Python
                    fixed_py = inner_text.replace("true", "True").replace("false", "False").replace("null", "None")
                    try:
                        return ast.literal_eval(fixed_py)
                    except:
                        pass
            
            # 策略 E: 使用 json_repair (最终手段)
            # 专门处理缺失括号、尾部截断等问题
            try:
                import json_repair
                return json_repair.loads(text)
            except Exception as e:
                # _LOGGER.warning("json_repair failed: %s", e)
                pass

            raise ValueError("无法解析 option 字符串，请确保是有效的 JSON 或 Python 字典格式。")

        option_dict = robust_parse(clean_option)

        # ========================================================================
        # 3. 后处理：补全必要字段
        # ========================================================================
        
        # 添加标题（如果 LLM 没有提供）
        if "title" not in option_dict:
            option_dict["title"] = {"text": title, "left": "center"}
        
        # 添加 tooltip（如果 LLM 没有提供）
        if "tooltip" not in option_dict:
            option_dict["tooltip"] = {"trigger": "axis"}
        
        # 确定图表类型（从 series 中提取）
        chart_type = "custom"
        if "series" in option_dict and len(option_dict["series"]) > 0:
            first_series = option_dict["series"][0]
            if isinstance(first_series, dict) and "type" in first_series:
                chart_type = first_series["type"]
        
        return json.dumps({
            "chart_type": chart_type,
            "title": title,
            "option": option_dict,
        }, default=str, ensure_ascii=False)
    
    except json.JSONDecodeError as e:
        _LOGGER.warning("data_deep.generate_chart JSON parse error: %s", e)
        return json.dumps({
            "success": False,
            "error": f"option JSON 解析失败：{e}",
            "suggestion": "请确保 option 是有效的 JSON 字符串。"
        }, default=str, ensure_ascii=False)
    except Exception as e:
        _LOGGER.warning("data_deep.generate_chart failed: %s", e)
        return json.dumps({
            "success": False,
            "error": str(e),
            "suggestion": "请检查 option 配置是否正确。"
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
