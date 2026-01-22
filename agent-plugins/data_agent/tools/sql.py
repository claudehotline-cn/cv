from __future__ import annotations

import json
import logging
import uuid
import os
import pandas as pd
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from agent_core.settings import get_settings
from agent_core.settings import get_settings
from data_agent.utils.db_utils import get_sql_database, run_sql_query, load_schema_preview
from data_agent.utils.artifacts import store_dataframe, save_sql_csv
from data_agent.schemas import SQLResultSchema
from agent_core.runtime import build_chat_llm

_LOGGER = logging.getLogger("agent_langchain.tools.sql")
_SQL_REVIEW_ENABLED = True


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


def _review_sql_logic(sql: str, schema_info: str, user_requirement: str = "") -> Dict[str, Any]:
    """使用 LLM 审核 SQL 逻辑是否正确。"""
    review_prompt = f"""你是 SQL 审核专家。审核以下 SQL 是否存在逻辑错误，并判断是否符合用户需求。

**用户需求**：
{user_requirement if user_requirement else '（未提供）'}

**数据库 Schema**：
{schema_info}

**待审核 SQL**：
```sql
{sql}
```

**审核清单**：
1. **JOIN 关联正确性**：JOIN 条件是否通过正确的外键关联？是否会产生笛卡尔积？
2. **语义正确性**（最重要）：
   - SELECT 的字段必须来自语义正确的表。根据 Schema 中的外键关系判断。
   - 如果用户要查某个维度的统计（如城市、类别），SELECT 的名称字段必须来自该维度的最终表，不能来自中间关联表。
   - SELECT 的别名应该反映其真实含义。
3. **聚合粒度**：
   - 如果用户需要"饼图/占比/分布"，SQL 应该只按一个维度聚合（如只 GROUP BY city_name）。
   - 如果用户需要"趋势图/时序图"，SQL 应该包含时间维度聚合。
4. **GROUP BY (宽松模式)**：只要 SELECT 中的非聚合列在 GROUP BY 中出现且逻辑正确，就通过。

**回复格式**（必须是有效 JSON）：
{{"approved": true, "issues": [], "suggestion": ""}}
或
{{"approved": false, "issues": ["问题描述"], "suggestion": "建议的修复方式"}}

只返回 JSON，不要其他内容。"""

    try:
        llm = build_chat_llm(task_name="sql_review")
        
        # Use Standard Content Block (Best Practice #4)
        from langchain_core.messages import HumanMessage
        messages = [
            HumanMessage(content=[
                {"type": "text", "text": review_prompt}
            ])
        ]
        
        response = llm.with_config({"tags": ["agent:sql_agent"]}).invoke(messages)
        
        from data_agent.utils.message_utils import extract_text_from_message
        content = extract_text_from_message(response).strip()
        
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            _LOGGER.info(f"SQL Review Result: {json.dumps(result, ensure_ascii=False)}")
            return result
        return {"approved": True, "issues": [], "suggestion": ""}
            
    except Exception as e:
        _LOGGER.warning("SQL review failed: %s", e)
        return {"approved": True, "issues": [], "suggestion": ""}


def _save_sql_result_csv(rows: List[Dict], columns: List[str], analysis_id: str, user_id: str = "anonymous") -> str:
    return save_sql_csv(rows, columns, analysis_id, user_id=user_id)


@tool("data_db_list_tables")
def db_list_tables_tool() -> str:
    """列出当前默认数据库中的候选表及其部分列信息。"""
    settings = get_settings()
    raw_db_name = getattr(settings, "db_default_name", None)
    if not raw_db_name:
        raise RuntimeError("未配置 db_default_name")
    db_name = settings.db_extra_databases.get(raw_db_name, raw_db_name)

    schema = load_schema_preview(db_name=db_name, max_tables=16, max_rows=0)
    tables_payload = [{"name": t.name, "columns": t.columns, "foreign_keys": t.foreign_keys} for t in schema.tables]
    return json.dumps({"db_name": db_name, "tables": tables_payload}, default=str, ensure_ascii=False)


@tool("data_db_table_schema")
def db_table_schema_tool(table: str) -> str:
    """查看默认数据库中某个表的列信息与少量样本数据。"""
    if not table or not table.strip():
        raise ValueError("表名不能为空。")

    settings = get_settings()
    raw_db_name = getattr(settings, "db_default_name", None)
    if not raw_db_name:
        raise RuntimeError("未配置 db_default_name")
    db_name = settings.db_extra_databases.get(raw_db_name, raw_db_name)

    schema = load_schema_preview(db_name=db_name, max_tables=64, max_rows=5)
    target = next((t for t in schema.tables if t.name == table), None)
    if target is None:
        raise ValueError(f"表 {table!r} 不存在")

    return json.dumps({
        "db_name": db_name,
        "table": target.name,
        "columns": target.columns,
        "foreign_keys": target.foreign_keys,
        "sample_rows": target.sample_rows,
    }, default=str, ensure_ascii=False)


@tool("data_db_run_sql")
def db_run_sql_tool(
    sql: str, 
    analysis_id: Optional[str] = None,
    user_requirement: Optional[str] = None,
    config: RunnableConfig = None
) -> str:
    """在默认数据库上执行一条只读 SQL，并返回结果表。
    
    Args:
        sql: 要执行的 SQL 语句
        analysis_id: 分析任务 ID（用于持久化结果）
        user_requirement: 用户的原始需求描述（用于审核 SQL 是否符合需求）
    """
    user_id = "anonymous"
    if config:
        user_id = config.get("configurable", {}).get("user_id", "anonymous")
    
    _LOGGER.info(f"[DEBUG] db_run_sql_tool: analysis_id={analysis_id}, user_id={user_id}, config_keys={list(config.keys()) if config else 'None'}")

    if not sql or not sql.strip():
        raise ValueError("SQL 不能为空。")

    settings = get_settings()
    raw_db_name = getattr(settings, "db_default_name", None)
    if not raw_db_name:
        raise RuntimeError("未配置 db_default_name")
    db_name = settings.db_extra_databases.get(raw_db_name, raw_db_name)

    # SQL Review
    if _SQL_REVIEW_ENABLED:
        _LOGGER.info(f"Running SQL Review for: {sql}")
        schema_info = _get_schema_for_review()
        review = _review_sql_logic(sql, schema_info, user_requirement or "")
        if not review.get("approved", True):
            return json.dumps({
                "success": False, "error": "SQL 审核不通过",
                "issues": review.get("issues"), "suggestion": review.get("suggestion")
            }, ensure_ascii=False)

    try:
        sql_db = get_sql_database(db_name)
        max_rows = getattr(settings, "excel_max_chart_rows", 500) or 500
        result = run_sql_query(db=sql_db, sql=sql, max_rows=max_rows, db_name=db_name)
        
        df = pd.DataFrame(result.rows, columns=result.columns)
        
        # 打印 SQL 结果到日志（前5行）
        _LOGGER.info(f"[SQL EXECUTION] SQL: {sql}")
        _LOGGER.info(f"[SQL RESULT PREVIEW] Shape: {df.shape}")
        if not df.empty:
            _LOGGER.info(f"[SQL RESULT SAMPLE]\n{df.head(5).to_string(index=False)}")
        else:
            _LOGGER.info("[SQL RESULT] Empty result set")
        
        # 存储到工作区（Parquet）
        # 存储到工作区（Parquet）
        if analysis_id:
            store_dataframe("sql_result", df, analysis_id, user_id=user_id)
            save_sql_csv(result.rows, result.columns, analysis_id, user_id=user_id)

        result_data = SQLResultSchema(
            success=True,
            columns=list(result.columns),
            rows=result.rows[:100],
            total_rows=len(result.rows),
        ).model_dump(mode='json')

        if len(result.rows) == 0:
            result_data["warning"] = "结果为空"

        return json.dumps(result_data, ensure_ascii=False, default=str)

    except Exception as e:
        return SQLResultSchema(success=False, columns=[], rows=[], total_rows=0, error=str(e)).model_dump_json()
