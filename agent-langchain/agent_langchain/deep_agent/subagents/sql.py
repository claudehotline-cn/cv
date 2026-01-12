"""SQL Sub-Agent Module"""
from __future__ import annotations

import logging
import operator
import re
import json
from typing import TypedDict, Annotated, Sequence, Any

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from deepagents import CompiledSubAgent

from ...llm_runtime import build_chat_llm
from ..tools import (
    db_list_tables_tool, db_table_schema_tool, db_run_sql_tool
)
from ..prompts import (
    SQL_AGENT_DESCRIPTION, SQL_AGENT_PROMPT
)

_LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# SQL Agent Definition
# -------------------------------------------------------------------------

class SQLAgentState(TypedDict):
    """SQL Agent 的状态"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    task_description: str
    analysis_id: str
    tables_info: str       # Step 1: 表列表
    schema_info: str       # Step 2: 表结构
    generated_sql: str     # Step 3: LLM 生成的 SQL
    sql_result: str        # Step 4: 执行结果
    retry_count: int        # 重试次数
    error_feedback: str     # 错误反馈

def sql_step1_list_tables(state: SQLAgentState) -> dict:
    """Step 1: 列出所有表"""
    _LOGGER.info("[SQL Agent Fixed Flow] Step 1: list_tables")
    
    analysis_id = state.get("analysis_id", "")
    task_description = ""
    
    messages = state.get("messages", [])
    for msg in messages:
        content = getattr(msg, "content", "") if hasattr(msg, "content") else str(msg)
        match = re.search(r'\[analysis_id[=:]?\s*([^\]]+)\]', content, re.IGNORECASE)
        if match:
            analysis_id = match.group(1).strip()
        task_description = content  # 最后一条消息作为任务描述
    
    try:
        result = db_list_tables_tool.invoke({"analysis_id": analysis_id})
        _LOGGER.info("[SQL Agent] list_tables result: %s", result[:300] if len(result) > 300 else result)
        return {"tables_info": result, "analysis_id": analysis_id, "task_description": task_description}
    except Exception as e:
        _LOGGER.error("[SQL Agent] list_tables failed: %s", e)
        return {"tables_info": f"Error: {e}", "analysis_id": analysis_id, "task_description": task_description}

def sql_step2_get_schema(state: SQLAgentState) -> dict:
    """Step 2: 获取相关表的 Schema"""
    _LOGGER.info("[SQL Agent Fixed Flow] Step 2: get_schema")
    
    tables_info = state.get("tables_info", "")
    
    # 从 tables_info JSON 中提取所有表名
    table_names = []
    try:
        tables_json = json.loads(tables_info) if isinstance(tables_info, str) else tables_info
        if isinstance(tables_json, dict) and "tables" in tables_json:
            for t in tables_json.get("tables", []):
                if isinstance(t, dict) and "name" in t:
                    table_names.append(t["name"])
    except:
        # Fallback: 正则提取
        table_names = re.findall(r'"name":\s*"([^"]+)"', tables_info)
    
    # 过滤只保留以 m_ 开头的业务表（排除系统表）
    business_tables = [t for t in table_names if t.startswith("m_")]
    _LOGGER.info("[SQL Agent] Found %d business tables: %s", len(business_tables), business_tables)
    
    # 获取所有业务表的 Schema
    schema_results = []
    for table in business_tables:
        try:
            result = db_table_schema_tool.invoke({"table": table})
            schema_results.append(f"表 {table}:\n{result}")
            _LOGGER.info("[SQL Agent] Got schema for table %s: %s", table, result[:200] if len(result) > 200 else result)
        except Exception as e:
            _LOGGER.error("[SQL Agent] Failed to get schema for %s: %s", table, e)
    
    schema_info = "\n\n".join(schema_results)
    _LOGGER.info("[SQL Agent] Total schema_info length: %d, tables: %d", len(schema_info), len(schema_results))
    return {"schema_info": schema_info}

def sql_step3_generate_sql(state: SQLAgentState) -> dict:
    """Step 3: LLM 根据表结构生成 SQL"""
    _LOGGER.info("[SQL Agent Fixed Flow] Step 3: LLM generate SQL")
    
    task = state.get("task_description", "")
    schema_info = state.get("schema_info", "")
    
    # 构建 Prompt
    prompt = SQL_AGENT_PROMPT.format(
        db_schema=schema_info,
        user_requirement=task
    )
    
    # --- 重试逻辑：如果有错误反馈，添加到 Prompt ---
    error_feedback = state.get("error_feedback", "")
    if error_feedback:
        _LOGGER.warning("[SQL Agent] Retrying with error feedback: %s", error_feedback[:200])
        prompt += f"""
sql
【上一次生成的 SQL 执行错误】
错误信息: {error_feedback}

请修正上述 SQL，确保逻辑正确且符合语法。
Strictly result ONLY the SQL code.
"""
    # ---------------------------------------------
    
    # 重新获取 LLM (因为不在闭包中)
    llm = build_chat_llm(task_name="data_deep_subagent")
    
    # 使用 System + Human 结构，明确角色防止 "Assistant" 幻觉
    messages = [
        SystemMessage(content="You are a strict SQL Code Generator. You must output ONLY valid SQL code. Do not start with 'Assistant:'."),
        HumanMessage(content=[
            {"type": "text", "text": prompt + "\n\nCRITICAL: Output ONLY the SQL query. Start immediately with ```sql"}
        ])
    ]
    
    # DEBUG: Log message structure before LLM call (using content_blocks)
    for i, m in enumerate(messages):
        blocks = getattr(m, 'content_blocks', [])
        _LOGGER.info(f"[SQL DEBUG] Message[{i}] role={type(m).__name__}, content_blocks_count={len(blocks)}")
        if blocks:
            first_block_type = blocks[0].get('type') if isinstance(blocks[0], dict) else type(blocks[0]).__name__
            _LOGGER.info(f"[SQL DEBUG] Message[{i}] first_block_type={first_block_type}")
    
    response = llm.invoke(messages)
    
    # DEBUG: Log response structure (using content_blocks)
    resp_blocks = getattr(response, 'content_blocks', [])
    _LOGGER.info(f"[SQL DEBUG] Response content_blocks_count={len(resp_blocks)}")
    
    from ...utils.message_utils import extract_text_from_message
    sql_content = extract_text_from_message(response)
    
    _LOGGER.info("[SQL Agent] Raw LLM response: %s", sql_content[:500] if sql_content else "(empty)")
    _LOGGER.debug("[SQL Agent] Full prompt sent to LLM: %s", prompt[:1000])
    
    # 改进 SQL 提取逻辑
    extracted_sql = sql_content.strip()
    
    # 1. 尝试提取 ```sql ... ```
    if "```sql" in sql_content:
        extracted_sql = sql_content.split("```sql")[1].split("```")[0].strip()
    # 2. 尝试提取 ``` ... ``` (通用代码块)
    elif "```" in sql_content:
        extracted_sql = sql_content.split("```")[1].split("```")[0].strip()
    # 3. 如果没有代码块，尝试查找 SELECT ... ; 或 SELECT ...
    elif "SELECT" in sql_content.upper():
        match = re.search(r'(SELECT[\s\S]+)', sql_content, re.IGNORECASE)
        if match:
             extracted_sql = match.group(1).strip()
    
    # 特殊处理：如果结果是 "Assistant" 或过短，视为生成失败
    if len(extracted_sql) < 10 or "Assistant" in extracted_sql:
        _LOGGER.warning("[SQL Agent] Generated SQL is invalid/empty: %s", extracted_sql)
        extracted_sql = "" # 清空，触发 run_sql 报错重试
    
    _LOGGER.info("[SQL Agent] Extracted SQL: %s", extracted_sql[:100])
    return {"generated_sql": extracted_sql}

def sql_step4_run_sql(state: SQLAgentState) -> dict:
    """Step 4: 执行 SQL"""
    _LOGGER.info("[SQL Agent Fixed Flow] Step 4: run_sql")
    
    sql = state.get("generated_sql", "")
    analysis_id = state.get("analysis_id", "")
    task_description = state.get("task_description", "")
    
    retry_count = state.get("retry_count", 0)
    
    if not sql:
        return {
            "sql_result": "Error: No SQL generated or SQL is invalid.",
            "retry_count": retry_count + 1,
            "error_feedback": "Previous attempt failed to generate valid SQL. Please generate a valid SELECT statement."
        }
    
    try:
        # 传入 user_requirement 以启用 SQL 审查
        result = db_run_sql_tool.invoke({
            "sql": sql, 
            "analysis_id": analysis_id,
            "user_requirement": task_description
        })
        _LOGGER.info("[SQL Agent] SQL execution result: %s", result[:500] if len(result) > 500 else result)
        
        # 检查是否包含 Error 或 Success=False
        is_success = True
        error_msg = ""
        try:
             res_json = json.loads(result) if isinstance(result, str) else result
             # 检查 SQL Review 失败 或 运行时错误
             if isinstance(res_json, dict):
                 if not res_json.get("success", True): # 有些 tool 返回 {success: False}
                     is_success = False
                     error_msg = res_json.get("error", "Unknown error")
                     if "issues" in res_json:
                         error_msg += f" Issues: {res_json['issues']}"
        except:
            pass
            
        if not is_success:
             _LOGGER.warning("[SQL Agent] Execution/Review failed: %s", error_msg)
             return {
                "sql_result": result,
                "retry_count": retry_count + 1,
                "error_feedback": error_msg
            }
            
        return {"sql_result": result, "error_feedback": ""} # 成功清除错误
        
    except Exception as e:
        _LOGGER.error("[SQL Agent] SQL execution failed: %s", e)
        return {
            "sql_result": f"Error: {e}",
            "retry_count": retry_count + 1,
            "error_feedback": str(e)
        }

def sql_format_output(state: SQLAgentState) -> dict:
    """格式化输出"""
    sql_result = state.get("sql_result", "")
    output = f"SQL_AGENT_COMPLETE: {sql_result}"
    return {"messages": [AIMessage(content=output)]}

def check_sql_retry(state: SQLAgentState) -> str:
    """检查是否需要重试"""
    retry_count = state.get("retry_count", 0)
    error_feedback = state.get("error_feedback", "")
    
    if error_feedback and retry_count < 3:
        _LOGGER.info("[SQL Agent] Retrying... Attempt %d", retry_count + 1)
        return "retry"
    return "continue"

# 构建 SQL 固化流程图
sql_agent_graph = StateGraph(SQLAgentState)
sql_agent_graph.add_node("list_tables", sql_step1_list_tables)
sql_agent_graph.add_node("table_schema", sql_step2_get_schema)
sql_agent_graph.add_node("llm_generate_sql", sql_step3_generate_sql)
sql_agent_graph.add_node("run_sql", sql_step4_run_sql)
sql_agent_graph.add_node("format_output", sql_format_output)

sql_agent_graph.add_edge(START, "list_tables")
sql_agent_graph.add_edge("list_tables", "table_schema")
sql_agent_graph.add_edge("table_schema", "llm_generate_sql")
sql_agent_graph.add_edge("llm_generate_sql", "run_sql")

sql_agent_graph.add_conditional_edges(
    "run_sql",
    check_sql_retry,
    {
        "retry": "llm_generate_sql",
        "continue": "format_output"
    }
)
sql_agent_graph.add_edge("format_output", END)

sql_agent_runnable = sql_agent_graph.compile()

sql_agent = CompiledSubAgent(
    name="sql_agent",
    description=SQL_AGENT_DESCRIPTION,
    runnable=sql_agent_runnable,
)
