from __future__ import annotations

import logging
from typing import Any, Dict, List

from langchain_core.messages import BaseMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from .config import get_settings
from .db.graph import invoke_db_chart_agent
from .db.loader import load_schema_preview
from .db.schema import DbAnalysisRequest, DbAgentResponse
from .db.sql_agent import get_sql_database, run_sql_query

_LOGGER = logging.getLogger("agent_langchain.db_deep")


def _build_charts_payload(response: DbAgentResponse) -> List[Dict[str, Any]]:
    """将 DbAgentResponse 中的图表结果转换为通用 JSON 结构。

    该结构与 db_chat_graph 中注入给前端的 __cv_charts 兼容：
      - id/title/description
      - option：原始 ECharts option
      - dataset_source：ECharts dataset.source（二维数组）
      - series_dimension：若存在 dataset.transform.config.dimension，则填入该字段
    """

    charts_payload: List[Dict[str, Any]] = []
    for chart in response.charts or []:
        try:
            option = getattr(chart, "option", None) or {}
            dataset = option.get("dataset", {})

            dataset_source = None
            if isinstance(dataset, dict):
                dataset_source = dataset.get("source")
            elif isinstance(dataset, list) and dataset:
                first_dataset = dataset[0] or {}
                if isinstance(first_dataset, dict):
                    dataset_source = first_dataset.get("source")

            series_dimension: str | None = None
            if isinstance(dataset, list) and len(dataset) > 1:
                for ds in dataset[1:]:
                    if not isinstance(ds, dict):
                        continue
                    transform = ds.get("transform") or {}
                    if not isinstance(transform, dict):
                        continue
                    config = transform.get("config") or {}
                    if not isinstance(config, dict):
                        continue
                    dimension = config.get("dimension")
                    if isinstance(dimension, str) and dimension:
                        series_dimension = dimension
                        break

            charts_payload.append(
                {
                    "id": chart.id,
                    "title": chart.title,
                    "description": chart.description,
                    "option": option,
                    "dataset_source": dataset_source,
                    "series_dimension": series_dimension,
                }
            )
        except Exception as exc:  # pragma: no cover - 防御性
            _LOGGER.warning(
                "db_deep.serialize_chart_failed id=%s error=%s",
                getattr(chart, "id", None),
                exc,
            )
            continue

    return charts_payload


@tool("db_list_tables")
def db_list_tables_tool() -> Dict[str, Any]:
    """列出当前默认数据库中的候选表及其部分列信息。

    返回：
      {
        "db_name": "...",
        "tables": [
          {
            "name": "orders",
            "columns": ["id", "user_id", "amount", ...]
          },
          ...
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
    tables_payload: List[Dict[str, Any]] = []
    for t in schema.tables:
        tables_payload.append(
            {
                "name": t.name,
                "columns": t.columns,
            }
        )

    _LOGGER.info(
        "db_deep.db_list_tables_tool.done db_name=%s tables=%d",
        db_name,
        len(tables_payload),
    )

    return {
        "db_name": db_name,
        "tables": tables_payload,
    }


@tool("db_table_schema")
def db_table_schema_tool(table: str) -> Dict[str, Any]:
    """查看默认数据库中某个表的列信息与少量样本数据。

    参数：
      - table: 表名，例如 \"orders\"、\"users\"。

    返回：
      {
        "db_name": "...",
        "table": "orders",
        "columns": ["id", "user_id", "amount", ...],
        "sample_rows": [
          {"id": 1, "user_id": 100, "amount": 10.5, ...},
          ...
        ]
      }
    """

    if not table or not table.strip():
        raise ValueError("表名不能为空。")

    settings = get_settings()
    raw_db_name = getattr(settings, "db_default_name", None)
    if not raw_db_name:
        raise RuntimeError("未配置 db_default_name，无法查询表结构。")
    db_name = settings.db_extra_databases.get(raw_db_name, raw_db_name)

    schema = load_schema_preview(db_name=db_name, max_tables=64, max_rows=5)
    target = None
    for t in schema.tables:
        if t.name == table:
            target = t
            break
    if target is None:
        raise ValueError(f"在数据库 {db_name!r} 中未找到表 {table!r}。")

    _LOGGER.info(
        "db_deep.db_table_schema_tool.done db_name=%s table=%s columns=%d sample_rows=%d",
        db_name,
        table,
        len(target.columns),
        len(target.sample_rows),
    )

    return {
        "db_name": db_name,
        "table": target.name,
        "columns": target.columns,
        "sample_rows": target.sample_rows,
    }


@tool("db_run_sql")
def db_run_sql_tool(sql: str) -> Dict[str, Any]:
    """在默认数据库上执行一条只读 SQL，并返回结果表。

    要求：
      - 仅允许 SELECT 或 WITH 开头的查询；
      - 必须包含 FROM 子句（或 CTE 中的 SELECT/FROM），禁止任何写操作。

    参数：
      - sql: 完整的 SQL 查询语句，例如：
        \"\"\"SELECT city, SUM(amount) AS total_amount FROM orders GROUP BY city\"\"\"。

    返回：
      {
        "db_name": "...",
        "sql": "SELECT ...",
        "columns": [...],
        "rows": [[...], ...]
      }
    行数会被限制在最大 max_rows 以内（默认 500），以保护数据库与前端性能。
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
    except Exception as exc:  # pragma: no cover - 防御性
        _LOGGER.error("db_deep.db_run_sql_tool.get_sql_database_failed db_name=%s error=%s", db_name, exc)
        raise

    max_rows = getattr(settings, "excel_max_chart_rows", 500) or 500
    if max_rows <= 0:
        max_rows = 500

    _LOGGER.info("db_deep.db_run_sql_tool.start db_name=%s", db_name)
    result = run_sql_query(
        db=sql_db,
        sql=sql,
        max_rows=max_rows,
        db_name=db_name,
    )
    _LOGGER.info(
        "db_deep.db_run_sql_tool.done db_name=%s rows=%d columns=%d",
        db_name,
        len(result.rows),
        len(result.columns),
    )

    return {
        "db_name": db_name,
        "sql": result.sql,
        "columns": list(result.columns),
        "rows": result.rows,
    }


@tool("db_chart")
def db_chart_tool(question: str) -> Dict[str, Any]:
    """使用 SQL Agent 对数据库进行分析并生成图表与结论。

    参数：
      - question: 用户以自然语言描述的数据库分析需求，例如
        “按月份统计订单金额和订单数，画一个双折线图”。
    返回：
      - 一个 JSON 对象，包含：
        {
          "used_db_name": "...",
          "insight": "整体分析结论文本",
          "charts": [  // 与 __cv_charts 兼容的结构数组
            {
              "id": "...",
              "title": "...",
              "description": "...",
              "option": {...},           // ECharts option
              "dataset_source": [...],   // dataset.source
              "series_dimension": "..."  // 若有
            },
            ...
          ]
        }
    """

    if not question or not question.strip():
        raise ValueError("问题描述不能为空，请提供需要分析的数据库问题。")

    _LOGGER.info("db_deep.db_chart_tool.start question=%s", question)

    request = DbAnalysisRequest(
        session_id="db_deep_agent",
        query=question.strip(),
        db_name=None,
    )
    response = invoke_db_chart_agent(request=request)

    charts_payload = _build_charts_payload(response)
    _LOGGER.info(
        "db_deep.db_chart_tool.done used_db_name=%s charts=%d sql_traces=%d",
        response.used_db_name,
        len(charts_payload),
        len(response.sql_traces or []),
    )

    return {
        "used_db_name": response.used_db_name,
        "insight": response.insight,
        "charts": charts_payload,
        "sql_traces": response.sql_traces,
    }


def get_db_deep_agent_graph() -> Any:
    """构造并返回一个基于 LLM + tools 的 LangGraph Deep Agent。

    - 模型：复用默认聊天模型（通过 build_chat_llm 构造）；
    - 工具：仅暴露一个 db_chart 工具，内部使用 SQL Agent + 图表规划器；
    - 状态：沿用 create_react_agent 默认的 messages 状态，适配 Agent Chat UI。
    """

    # 延迟导入，避免循环依赖
    from .llm_runtime import build_chat_llm

    model = build_chat_llm(task_name="db_deep_agent")

    # 为 Deep Agent 提供明确的系统指令，约束工具使用顺序与策略：
    # 1) 优先使用 db_list_tables / db_table_schema 理解库结构；
    # 2) 需要执行查询时，根据用户是否提供 SQL 选择 db_run_sql，或引导用户显式给出 SQL；
    # 3) 只有在需要可视化且已获得结构化结果时，才调用 db_chart 生成图表；
    # 4) 不要在尚未理解表结构与字段含义时直接调用 db_chart。
    instructions = (
        "你是一个数据库 Deep Agent，负责使用一组数据库相关工具完成用户的分析需求，并清晰暴露工具调用过程。\n\n"
        "【可用工具】\n"
        "1) db_list_tables：列出默认数据库中的候选表和列名，用于了解有哪些表。\n"
        "2) db_table_schema：查看某个表的列信息和少量样本数据，用于理解字段含义和分布。\n"
        "3) db_run_sql：在只读安全壳内执行用户提供的完整 SQL（仅允许 SELECT/WITH 查询）。\n"
        "4) db_chart：在已有的结构化结果基础上调用数据库图表 Agent，生成 ECharts 图表与分析结论。\n\n"
        "【使用策略】\n"
        "1) 当用户提出数据库分析问题时，先使用 db_list_tables 和/或 db_table_schema 理解相关表结构，"
        "   再决定如何编写或生成 SQL；不要在不了解表结构的情况下直接执行查询。\n"
        "2) 若用户直接给出了 SQL，则优先使用 db_run_sql 执行该 SQL；若用户仅给出自然语言问题，应先通过 db_list_tables/db_table_schema 弄清表结构，再在对话中明确提出要使用的表与字段，并构造 SQL，最后通过 db_run_sql 执行。\n"
        "3) 只有在需要可视化且已经有了明确的聚合结果时，才调用 db_chart 生成图表；\n"
        "   除非用户明确要求“直接生成图表”，否则不要一开始就调用 db_chart。\n"
        "4) 在整个过程中，可以多次调用上述工具，以逐步细化分析；每次工具调用的输入输出应尽量简洁、聚焦。\n"
    )

    graph = create_react_agent(
        model=model,
        tools=[
            db_list_tables_tool,
            db_table_schema_tool,
            db_run_sql_tool,
            db_chart_tool,
        ],
        prompt=instructions,
    )
    return graph
