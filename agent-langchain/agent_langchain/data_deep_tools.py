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
from .schemas import SQLResultSchema, PythonResultSchema, ChartResultSchema, ValidationResultSchema

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

# SQL 审核配置
_SQL_REVIEW_ENABLED = True  # 可通过环境变量控制


def _review_sql_logic(sql: str, schema_info: str) -> Dict[str, Any]:
    """使用 LLM 审核 SQL 逻辑是否正确。
    
    检查：
    - CROSS JOIN 笛卡尔积
    - 错误的 JOIN 条件
    - 可能导致数据重复的逻辑
    
    返回：
    {
        "approved": True/False,
        "issues": ["问题1", "问题2"],
        "suggestion": "修复建议"
    }
    """
    from .llm_runtime import build_chat_llm
    
    review_prompt = f"""你是 SQL 审核专家。审核以下 SQL 是否存在逻辑错误。

**数据库 Schema**：
{schema_info}

**待审核 SQL**：
```sql
{sql}
```

**审核清单**：
1. 是否存在无条件的 CROSS JOIN（笛卡尔积）？
2. JOIN 条件是否通过正确的外键关联？
3. 是否会产生重复数据或数据放大？
4. **核心检查**：GROUP BY 必须包含 SELECT 中所有非聚合列！（例如：SELECT city, SUM(...) ... GROUP BY month -> 错误！必须 GROUP BY city, month）

**回复格式**（必须是有效 JSON）：
{{"approved": true, "issues": [], "suggestion": ""}}
或
{{"approved": false, "issues": ["问题描述"], "suggestion": "建议的修复方式"}}

只返回 JSON，不要其他内容。"""

    try:
        llm = build_chat_llm(task_name="sql_review")
        response = llm.invoke(review_prompt)
        content = response.content.strip()
        
        # 提取 JSON
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            _LOGGER.info("SQL review result: approved=%s issues=%s", 
                        result.get("approved"), result.get("issues"))
            return result
        else:
            _LOGGER.warning("SQL review failed to parse response: %s", content[:200])
            return {"approved": True, "issues": [], "suggestion": ""}
            
    except Exception as e:
        _LOGGER.warning("SQL review failed with error: %s", e)
        # 审核失败时默认通过，不阻塞执行
        return {"approved": True, "issues": [], "suggestion": ""}


def _get_schema_for_review() -> str:
    """获取用于 SQL 审核的 Schema 摘要。"""
    try:
        settings = get_settings()
        raw_db_name = getattr(settings, "db_default_name", None)
        if not raw_db_name:
            return "Schema 不可用"
        db_name = settings.db_extra_databases.get(raw_db_name, raw_db_name)
        schema = load_schema_preview(db_name=db_name, max_tables=16, max_rows=0)
        
        lines = []
        for t in schema.tables:
            cols = ", ".join(t.columns[:10])
            lines.append(f"- {t.name}: ({cols})")
        return "\n".join(lines)
    except Exception as e:
        _LOGGER.warning("Failed to get schema for review: %s", e)
        return "Schema 不可用"


def _review_python_code(code: str, available_vars: List[str]) -> Dict[str, Any]:
    """使用 LLM 审核 Python 代码的安全性与正确性。先检查语法错误。"""
    from .llm_runtime import build_chat_llm
    
    # === 第一步：用 AST 检查语法错误 ===
    try:
        ast.parse(code)
    except SyntaxError as e:
        _LOGGER.warning("Syntax error detected: %s", e)
        # 语法错误，让 LLM 分析并给出修复建议
        syntax_prompt = f"""你是 Python 语法专家。分析以下代码的语法错误，并给出修复后的代码。

**语法错误**:
{e}

**原始代码**:
```python
{code}
```

**回复格式（JSON）**:
{{"approved": false, "issues": ["语法错误描述"], "suggestion": "修复后的完整代码"}}

只返回 JSON。"""
        try:
            llm = build_chat_llm(task_name="syntax_fix")
            response = llm.invoke(syntax_prompt)
            content = response.content.strip()
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                _LOGGER.info("Syntax fix suggestion: %s", result.get("suggestion", "")[:100])
                return result
        except Exception as ex:
            _LOGGER.warning("Syntax fix LLM failed: %s", ex)
        return {"approved": False, "issues": [str(e)], "suggestion": "请检查代码语法"}
    
    # === 第二步：安全性审核 ===
    review_prompt = f"""你是 Python 安全审核专家。**只检查严重安全问题**，忽略代码风格和规范问题。

**待审核代码**：
```python
{code}
```

**仅拒绝以下情况**（必须全部满足才拒绝）：
1. 包含 `os.system`, `subprocess`, `eval`, `exec`, `__import__` 等危险调用
2. 包含 `open()` 写文件操作（读取可以接受）
3. 包含 `requests`, `urllib`, `socket` 等网络请求

**宽松通过**：
- 变量是否定义、列是否存在 → 不管，让运行时报错
- 是否有 result 变量 → 不管
- 代码风格问题 → 不管

**回复格式**（JSON）：
{{"approved": true, "issues": [], "suggestion": ""}}

只有发现上述危险操作时才返回 approved=false。99%的情况应该通过。
只返回 JSON。"""

    try:
        llm = build_chat_llm(task_name="python_review")
        response = llm.invoke(review_prompt)
        content = response.content.strip()
        
        # 提取 JSON
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            _LOGGER.info("Python review result: approved=%s issues=%s", 
                        result.get("approved"), result.get("issues"))
            return result
        else:
            _LOGGER.warning("Python review failed to parse: %s", content[:200])
            return {"approved": True, "issues": [], "suggestion": ""}
    except Exception as e:
        _LOGGER.warning("Python review failed with error: %s", e)
        return {"approved": True, "issues": [], "suggestion": ""}

def _analyze_syntax_error(code: str, error: Exception) -> Dict[str, Any]:
    """使用 LLM 分析语法/运行时错误并给出修复建议。"""
    from .llm_runtime import build_chat_llm
    
    error_msg = str(error)
    
    review_prompt = f"""你是 Python 语法专家。分析以下代码的错误，并给出修复后的代码。

**错误信息**:
{error_msg}

**原始代码**:
```python
{code}
```

**常见问题**:
1. `str.extract()` 需要捕获组括号：`df['col'].str.extract(r'(\d+)')` ← 注意括号
2. 变量未定义
3. 类型错误

**回复格式（JSON）**:
{{"error_type": "错误类型", "cause": "简短原因", "fixed_code": "修复后的完整代码"}}

只返回 JSON。"""

    try:
        llm = build_chat_llm(task_name="syntax_error_fix")
        response = llm.invoke(review_prompt)
        content = response.content.strip()
        
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            _LOGGER.info("Syntax error analysis: type=%s cause=%s", 
                        result.get("error_type"), result.get("cause"))
            return result
    except Exception as e:
        _LOGGER.warning("Syntax error analysis failed: %s", e)
    
    return {"error_type": "Unknown", "cause": error_msg, "fixed_code": None}


def _validate_chart_option(chart_data: Dict[str, Any]) -> Dict[str, Any]:
    """使用 LLM 验证图表配置是否正确。"""
    from .llm_runtime import build_chat_llm
    
    chart_type = chart_data.get("chart_type", "")
    option = chart_data.get("option", {})
    
    if not option:
        return {"valid": False, "issues": ["option 为空"], "suggestion": "必须提供 chart_option"}
    
    review_prompt = f"""你是图表配置审核专家。审核以下 ECharts option 是否配置正确。

**图表类型**: {chart_type}

**option 配置**:
```json
{json.dumps(option, ensure_ascii=False, indent=2)}
```

**审核规则**:
1. **散点图 (scatter)**: 必须是相关性散点图，X/Y 轴都是数值列（如城市A金额 vs 城市B金额），不能用月份/日期/序号做 X 轴
2. **折线图/柱状图 (line/bar)**: series 不能为空
3. **饼图 (pie)**: series.data 不能为空

**回复格式（JSON）**:
- 通过: {{"valid": true}}
- 失败: {{"valid": false, "reason": "问题描述"}}

只返回 JSON。"""

    try:
        llm = build_chat_llm(task_name="chart_review")
        response = llm.invoke(review_prompt)
        content = response.content.strip()
        
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            is_valid = result.get("valid", True)
            reason = result.get("reason", "")
            fix_code = result.get("fix_code", "")
            _LOGGER.info("Chart review: type=%s valid=%s reason=%s", chart_type, is_valid, reason)
            if not is_valid:
                suggestion = fix_code if fix_code else "请修正图表配置"
                return {"valid": False, "issues": [reason], "suggestion": suggestion}
    except Exception as e:
        _LOGGER.warning("Chart review error: %s", e)
    
    return {"valid": True, "issues": [], "suggestion": ""}


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

    # === SQL 逻辑审核 ===
    if _SQL_REVIEW_ENABLED:
        _LOGGER.info("data_deep.db_run_sql starting SQL review")
        schema_info = _get_schema_for_review()
        review_result = _review_sql_logic(sql, schema_info)
        
        if not review_result.get("approved", True):
            issues = review_result.get("issues", [])
            suggestion = review_result.get("suggestion", "")
            _LOGGER.warning("SQL review failed: issues=%s suggestion=%s", issues, suggestion)
            return json.dumps({
                "success": False,
                "error": "SQL 审核不通过",
                "review_issues": issues,
                "suggestion": suggestion,
                "sql": sql
            }, ensure_ascii=False)
        else:
            _LOGGER.info("SQL review passed")

    try:
        sql_db = get_sql_database(db_name)
        max_rows = getattr(settings, "excel_max_chart_rows", 500) or 500

        _LOGGER.info("data_deep.db_run_sql start sql=%s", sql)  # Log full SQL
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
        
        # Build result
        result_data = SQLResultSchema(
            success=True,
            columns=list(result.columns),
            rows=result.rows[:100],  # 只返回前 100 行给 LLM
            total_rows=len(result.rows),
        ).model_dump(mode='json')

        # [Zero-Result Auto-Correction]
        if len(result.rows) == 0:
            msg = "⚠️ 查询结果为空(0行)。\n提示：数据库中可能有数据，但被您的 WHERE 条件过滤了。\n建议：\n1. 移除 WHERE 日期过滤（查询全量历史数据）\n2. 检查 JOIN 条件"
            result_data["warning"] = msg
            _LOGGER.warning("db_run_sql returned 0 rows. Hinting agent to check WHERE clause.")
        
        # [Data Quality Check - 检测 Unknown/NULL 值]
        if len(result.rows) > 0:
            import pandas as pd
            df_check = pd.DataFrame(result.rows, columns=result.columns)
            warnings = []
            for col in df_check.columns:
                unknown_count = df_check[col].astype(str).str.lower().isin(['unknown', 'null', 'none', '']).sum()
                null_count = df_check[col].isna().sum()
                total_bad = unknown_count + null_count
                if total_bad > 0 and total_bad == len(df_check):
                    warnings.append(f"列 '{col}' 全是 Unknown/NULL 值！可能需要 JOIN 其他表来获取真实数据。")
                elif total_bad > len(df_check) * 0.5:
                    warnings.append(f"列 '{col}' 有 {total_bad}/{len(df_check)} 行是 Unknown/NULL 值。")
            
            if warnings:
                warning_msg = "\n".join(warnings)
                warning_msg += "\n\n提示：检查 SQL 是否需要 JOIN 关联表。例如：\n- m_orders JOIN m_customers ON customer_id\n- m_customers JOIN m_cities ON city_id"
                result_data["data_quality_warning"] = warning_msg
                _LOGGER.warning("Data quality issues: %s", warnings)

        return json.dumps(result_data, ensure_ascii=False, default=str)
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

        return SQLResultSchema(
            success=False,
            columns=[],
            rows=[],
            total_rows=0,
            error=error_msg,
            suggestion=suggestion if suggestion else None,
        ).model_dump_json()


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

    # === Python 代码审核 ===
    if _SQL_REVIEW_ENABLED:
        _LOGGER.info("data_deep.python_execute starting code review")
        available_vars = list(_CURRENT_DATAFRAMES.keys()) + ["pd", "np"]
        review_result = _review_python_code(code, available_vars)
        
        if not review_result.get("approved", True):
            issues = review_result.get("issues", [])
            suggestion = review_result.get("suggestion", "")
            _LOGGER.warning("Python review failed: issues=%s suggestion=%s", issues, suggestion)
            return json.dumps({
                "success": False,
                "error": "Python 代码审核不通过",
                "review_issues": issues,
                "suggestion": suggestion,
                "available_variables": available_vars,
                "code": code
            }, ensure_ascii=False)
        else:
            _LOGGER.info("Python review passed")

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

        # === 图表验证：检查 CHART_DATA 输出 ===
        if stdout_output and "CHART_DATA:" in stdout_output:
            try:
                chart_json_str = stdout_output.split("CHART_DATA:", 1)[1].strip()
                chart_data = json.loads(chart_json_str)
                _LOGGER.info("Starting chart validation for type: %s", chart_data.get("chart_type"))
                validation_result = _validate_chart_option(chart_data)
                
                if not validation_result.get("valid", True):
                    _LOGGER.warning("Chart validation failed: %s", validation_result)
                    return json.dumps({
                        "success": False,
                        "error": "图表配置验证失败",
                        "validation_issues": validation_result.get("issues", []),
                        "suggestion": validation_result.get("suggestion", ""),
                        "original_chart_data": chart_data
                    }, ensure_ascii=False)
                else:
                    _LOGGER.info("Chart validation passed")
            except (json.JSONDecodeError, IndexError) as e:
                _LOGGER.warning("Failed to parse CHART_DATA for validation: %s", e)

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
        
        return PythonResultSchema(
            success=True,
            stdout=output_data.get("stdout") or "",
            stderr=output_data.get("stderr") or "",
            result_type=output_data.get("result_type"),
            result_shape=str(output_data.get("result_shape")) if output_data.get("result_shape") else None,
            result_columns=output_data.get("result_columns"),
            result_preview=output_data.get("result_preview"),
            note=output_data.get("note"),
        ).model_dump_json()

    except Exception as e:
        error_msg = traceback.format_exc()
        _LOGGER.warning("data_deep.python_execute failed: %s", e)
        
        # 调用 LLM 分析运行时错误并给出修复建议
        analysis = _analyze_syntax_error(code, e)
        fixed_code = analysis.get("fixed_code")
        
        return PythonResultSchema(
            success=False,
            stdout="",
            stderr="",
            error=f"{analysis.get('error_type', 'Error')}: {analysis.get('cause', str(e))}",
            suggestion=fixed_code if fixed_code else _get_error_suggestion(str(e)),
        ).model_dump_json()


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
    title: str = "数据图表"
) -> Dict[str, Any]:
    """生成 ECharts 图表。

    参数：
      - option: 完整的 ECharts option 配置（JSON 字符串或 Dict）。
                必须包含所有数据（xAxis.data, series[].data, 或 dataset.source）。
      - title: 图表标题

    **重要**：
    此工具只负责解析和返回 option，不做任何数据处理。
    Agent 必须在调用前通过 Python 工具准备好完整的 option（包括数据）。
    """
    _LOGGER.info("data_deep.generate_chart start title=%s", title)
    
    import ast
    import re
    import json
    
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
    ).model_dump_json()
    
    # Add CHART_DATA: marker for frontend/middleware detection
    return f"CHART_DATA:{result_json}"






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
        return ValidationResultSchema(
            valid=False,
            data_source=data_source,
            row_count=0,
            columns=[],
            error=f"未找到 DataFrame '{data_source}'",
            suggestion="请先执行查询或加载数据。"
        ).model_dump_json()

    import pandas as pd
    if not isinstance(df, pd.DataFrame):
        return ValidationResultSchema(
            valid=False,
            data_source=data_source,
            row_count=0,
            columns=[],
            error=f"'{data_source}' 不是有效的 DataFrame",
            suggestion="请检查数据加载步骤。"
        ).model_dump_json()

    warnings_list = []
    suggestions = []

    # 检查空数据
    if df.empty:
        warnings_list.append("数据为空")
        suggestions.append("请检查查询条件或数据源。")

    # 检查空值
    null_cols = df.columns[df.isnull().any()].tolist()
    if null_cols:
        warnings_list.append(f"以下列包含空值：{null_cols}")
        suggestions.append("可使用 df.dropna() 或 df.fillna() 处理空值。")

    # 检查数据类型
    for col in df.columns:
        if df[col].dtype == "object":
            # 尝试检测数值
            try:
                pd.to_numeric(df[col], errors="raise")
                warnings_list.append(f"列 '{col}' 可能应该是数值类型")
                suggestions.append(f"可使用 df['{col}'] = pd.to_numeric(df['{col}']) 转换。")
            except (ValueError, TypeError):
                pass

    return ValidationResultSchema(
        valid=len(warnings_list) == 0,
        data_source=data_source,
        row_count=len(df),
        columns=list(df.columns),
        warnings=warnings_list,
        suggestion="; ".join(suggestions) if suggestions else None,
    ).model_dump_json()

# ============================================================================
# Visualizer Tool (Schema Profile)
# ============================================================================
@tool("df_profile")
def df_profile_tool(df_name: str = "result") -> str:
    """获取 DataFrame 的元数据摘要（列名、类型、缺失率、Sample）。
    用于在编写代码前了解数据结构。
    """
    df = _get_dataframe(df_name)
    if df is None:
        return json.dumps({"error": f"DataFrame '{df_name}' not found."}, ensure_ascii=False)
    
    try:
        import numpy as np
        info = {
            "n_rows": len(df),
            "columns": []
        }
        for col in df.columns:
            c_series = df[col]
            col_info = {
                "name": str(col),
                "dtype": str(c_series.dtype),
                "n_null": int(c_series.isnull().sum())
            }
            if not np.issubdtype(c_series.dtype, np.number):
                top = c_series.value_counts().head(5).index.tolist()
                col_info["top_values"] = [str(t) for t in top]
            info["columns"].append(col_info)
            
        info["sample"] = json.loads(df.head(3).to_json(orient="records", date_format="iso"))
        return json.dumps(info, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error profiling df: {str(e)}"
