from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from sqlalchemy import text

from ..config import get_settings
from .schema import DbAnalysisRequest

_LOGGER = logging.getLogger("cv_agent.db.sql")


@dataclass
class SqlQueryResult:
    """SQL 查询结果结构。

    - sql: LLM 生成的最终 SQL 语句；
    - columns: 列名列表；
    - rows: 行数据，每行与 columns 一一对应。
    """

    sql: str
    columns: List[str]
    rows: List[List[Any]]


def _build_db_llm() -> Any:
    """构造用于 SQL 生成的 LLM 客户端。

    复用 Settings 中的 llm_provider/llm_model 配置：
    - openai：使用 ChatOpenAI，需要 OPENAI_API_KEY；
    - ollama：使用 ChatOllama，走本地/自建模型。
    """

    settings = get_settings()
    provider = getattr(settings, "llm_provider", "openai").lower()

    if provider == "ollama":
        _LOGGER.info(
            "db.sql.llm_init provider=ollama model=%s base_url=%s",
            settings.llm_model,
            getattr(settings, "ollama_base_url", "http://host.docker.internal:11434"),
        )
        return ChatOllama(
            model=settings.llm_model,
            base_url=getattr(settings, "ollama_base_url", "http://host.docker.internal:11434"),
        )

    # 默认走 openai 路径
    if not settings.openai_api_key:
        _LOGGER.error("db.sql.llm_init_failed provider=openai reason=missing_api_key")
        raise RuntimeError("OPENAI_API_KEY 未配置，无法生成数据库分析 SQL")

    _LOGGER.info(
        "db.sql.llm_init provider=openai model=%s",
        settings.llm_model,
    )
    return ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key)


def get_sql_database(db_name: str) -> SQLDatabase:
    """基于 Settings 构造 LangChain SQLDatabase 对象。

    当前仅支持 MySQL（pymysql），连接串示例：
    mysql+pymysql://user:password@host:port/db_name
    """

    settings = get_settings()
    host = getattr(settings, "db_host", "mysql")
    port = int(getattr(settings, "db_port", 3306))
    user = getattr(settings, "db_user", "root")
    password = getattr(settings, "db_password", "123456")

    # 注意：这里只做最小转义，复杂密码场景下建议使用 DSN 方式。
    from urllib.parse import quote_plus

    safe_password = quote_plus(password)
    uri = f"mysql+pymysql://{user}:{safe_password}@{host}:{port}/{db_name}"

    _LOGGER.info(
        "db.sql.get_sql_database uri=%s",
        uri.replace(safe_password, "***"),
    )
    return SQLDatabase.from_uri(uri)


def _ensure_safe_select_sql(sql: str) -> str:
    """对 LLM 生成的 SQL 做最小安全校验，仅允许只读查询。

    - 只允许以 SELECT / WITH 开头的语句；
    - 禁止出现 INSERT/UPDATE/DELETE/DDL 等高危关键字；
    - 如校验失败则抛出 ValueError。
    """

    stripped = sql.strip().strip(";")
    lowered = stripped.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError(f"仅允许 SELECT/WITH 查询，当前 SQL 为: {sql!r}")

    forbidden_keywords = (
        "insert ",
        "update ",
        "delete ",
        "drop ",
        "truncate ",
        "alter ",
        "create ",
        "merge ",
        "grant ",
        "revoke ",
    )
    for kw in forbidden_keywords:
        if kw in lowered:
            raise ValueError(f"SQL 中包含禁止关键字 {kw.strip()}: {sql!r}")

    return stripped


def _execute_sql(
    db: SQLDatabase,
    sql: str,
    max_rows: int,
    db_name: str | None = None,
) -> SqlQueryResult:
    """在 SQLDatabase 的底层 engine 上执行只读 SQL，并返回结构化结果。"""

    safe_sql = _ensure_safe_select_sql(sql)

    # SQLDatabase 在不同版本中 engine 属性名称可能不同，这里做一次兼容处理。
    engine = getattr(db, "engine", None) or getattr(db, "_engine", None)
    if engine is None:
        raise RuntimeError("SQLDatabase 缺少 engine 属性，无法执行 SQL 查询")

    import time

    start_ts = time.perf_counter()
    _LOGGER.info(
        "db.sql.execute_sql.start db_name=%s sql=%s max_rows=%d",
        db_name or "",
        safe_sql,
        max_rows,
    )

    columns: List[str] = []
    rows: List[List[Any]] = []

    with engine.connect() as conn:  # type: ignore[assignment]
        result = conn.execute(text(safe_sql))
        try:
            columns = list(result.keys())
        except Exception:
            # 某些驱动版本不支持 keys()，退回到 cursor.description 逻辑
            cursor = result.cursor  # type: ignore[attr-defined]
            columns = [c[0] for c in cursor.description]

        for idx, row in enumerate(result):
            if idx >= max_rows:
                break
            # row 可能是 Row/RowMapping，也可能是元组，这里按列名提取。
            try:
                row_data = [row[col] for col in columns]  # type: ignore[index]
            except Exception:
                row_data = list(row)  # type: ignore[list-item]
            rows.append(row_data)

    duration_ms = (time.perf_counter() - start_ts) * 1000.0
    _LOGGER.info(
        "db.sql.execute_sql.done db_name=%s rows=%d columns=%d duration_ms=%.1f",
        db_name or "",
        len(rows),
        len(columns),
        duration_ms,
    )
    return SqlQueryResult(sql=safe_sql, columns=columns, rows=rows)


def run_sql_query(
    db: SQLDatabase,
    sql: str,
    max_rows: int = 500,
    db_name: str | None = None,
) -> SqlQueryResult:
    """对外暴露的只读 SQL 执行接口，带最大行数与最小安全校验。"""

    if max_rows <= 0:
        max_rows = 500
    return _execute_sql(db=db, sql=sql, max_rows=max_rows, db_name=db_name)


def plan_and_run_sql(
    request: DbAnalysisRequest,
    db: SQLDatabase,
    db_name: str,
    max_rows: int = 500,
) -> List[SqlQueryResult]:
    """根据 DbAnalysisRequest 使用 LangChain SQL Agent 规划并执行一次只读 SQL。

    - 使用 create_sql_agent 基于 SQLDatabase 构建带工具调用能力的 AgentExecutor；
    - 要求 Agent 至少调用一次 sql_db_query 工具生成聚合查询；
    - 从 intermediate_steps 中提取最终 SQL，并由 run_sql_query 执行只读查询。
    """

    question = request.query
    if not question.strip():
        raise ValueError("DbAnalysisRequest.query 不能为空")

    settings = get_settings()
    timeout_sec = float(getattr(settings, "request_timeout_sec", 30.0))
    if max_rows <= 0:
        max_rows = getattr(settings, "excel_max_chart_rows", 500) or 500

    _LOGGER.info(
        "db.sql.plan_and_run_sql.start db_name=%s session_id=%s timeout_sec=%.1f max_rows=%d",
        db_name,
        request.session_id,
        timeout_sec,
        max_rows,
    )

    llm = _build_db_llm()

    # 基于 SQLDatabase 构建 AgentExecutor（工具型 SQL Agent），开启中间步骤输出。
    agent = create_sql_agent(
        llm=llm,
        db=db,
        agent_type="zero-shot-react-description",
        verbose=False,
        agent_executor_kwargs={
            "return_intermediate_steps": True,
        },
    )

    def _invoke_agent() -> Dict[str, Any]:
        prompt = (
            "你是数据库分析 SQL Agent。请严格按照以下步骤工作：\n"
            "1. 可以先使用 sql_db_list_tables 和 sql_db_schema 工具了解有哪些表和字段；\n"
            "2. 然后必须至少调用一次 sql_db_query 工具，编写并执行一条只读的聚合查询 SQL；\n"
            "3. 该 SQL 必须只包含 SELECT 或 WITH 语句，不得包含任何 INSERT/UPDATE/DELETE/DDL 或事务相关语句；\n"
            "4. 优先使用 SUM/COUNT/AVG 等聚合函数和 GROUP BY，并根据用户问题选择合理的时间范围和维度；\n"
            "5. 完成工具调用后，用简短中文回答结果；并在回答结尾追加一段 ```sql ... ``` 代码块，给出最终用于查询的数据 SQL；\n"
            "6. 该 SQL 必须能够直接在当前数据库中执行，且满足用户问题需求。\n\n"
            f"用户问题：{question}"
        )
        result = agent.invoke({"input": prompt})  # type: ignore[call-arg]
        if isinstance(result, dict):
            return result
        return {"output": str(result)}

    def _extract_sql_from_steps(result: Dict[str, Any]) -> str | None:
        """从 AgentExecutor 的 intermediate_steps 或最终输出中提取 SQL。"""

        steps = result.get("intermediate_steps") or []

        def _get_sql_from_action(action: Any) -> str | None:
            # dict 形式
            if isinstance(action, dict):
                tool_name = action.get("tool") or action.get("name")
                if not tool_name:
                    return None
                name_str = str(tool_name).lower()
                if not any(
                    key in name_str
                    for key in (
                        "sql_db_query",
                        "sql-db-query",
                        "sql_db_query_checker",
                        "sql-db-query-checker",
                        "query_checker",
                        "query-checker",
                    )
                ):
                    return None
                sql_candidate = (
                    action.get("tool_input")
                    or action.get("input")
                    or action.get("args")
                )
                return str(sql_candidate) if sql_candidate else None

            # 对象形式（AgentAction）
            tool_name = getattr(action, "tool", None) or getattr(action, "name", None)
            if not tool_name:
                return None
            name_str = str(tool_name).lower()
            if not any(
                key in name_str
                for key in (
                    "sql_db_query",
                    "sql-db-query",
                    "sql_db_query_checker",
                    "sql-db-query-checker",
                    "query_checker",
                    "query-checker",
                )
            ):
                return None
            sql_candidate = getattr(action, "tool_input", None)
            if not sql_candidate:
                sql_candidate = getattr(action, "input", None) or getattr(action, "args", None)
            return str(sql_candidate) if sql_candidate else None

        # 1) 按逆序遍历 intermediate_steps，优先取最近一次 sql_db_query 调用。
        for item in reversed(steps):
            if isinstance(item, (list, tuple)) and item:
                sql = _get_sql_from_action(item[0])
                if sql:
                    return sql
                continue
            sql = _get_sql_from_action(item)
            if sql:
                return sql

        # 2) 若从 intermediate_steps 中未能提取，则尝试从最终 output 文本中抽取 SQL。
        output = result.get("output")
        if isinstance(output, str) and output:
            import re

            # 先尝试从 ```sql ... ``` 代码块中提取，若无则退回到全文搜索。
            code_block_matches = list(
                re.finditer(r"```sql(.*?)(```|$)", output, flags=re.IGNORECASE | re.DOTALL)
            )
            search_targets: List[str] = []
            if code_block_matches:
                for m in code_block_matches:
                    search_targets.append(m.group(1))
            else:
                search_targets.append(output)

            last_match_sql: str | None = None
            for text_block in search_targets:
                for m in re.finditer(
                    r"(?is)\b(select|with)\b.+?(?:;|\n|$)",
                    text_block,
                ):
                    last_match_sql = m.group(0)

            if last_match_sql:
                return last_match_sql.strip().rstrip(";")
        return None

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_invoke_agent)
        try:
            agent_result = future.result(timeout=timeout_sec)
        except FuturesTimeoutError as exc:
            _LOGGER.error(
                "db.sql.plan_and_run_sql.timeout db_name=%s session_id=%s timeout_sec=%.1f",
                db_name,
                request.session_id,
                timeout_sec,
            )
            raise TimeoutError(f"生成数据库查询 SQL 超时（>{timeout_sec}s）") from exc

    # 记录中间步骤的工具调用概览，便于排查 SQL Agent 行为。
    steps = agent_result.get("intermediate_steps") or []
    steps_summary: List[Dict[str, Any]] = []
    for item in list(steps)[:5]:
        if isinstance(item, (list, tuple)) and item:
            action = item[0]
        else:
            action = item
        info: Dict[str, Any] = {
            "type": type(action).__name__,
            "tool": None,
        }
        if isinstance(action, dict):
            info["tool"] = action.get("tool") or action.get("name")
        else:
            info["tool"] = getattr(action, "tool", None) or getattr(action, "name", None)
        steps_summary.append(info)
    _LOGGER.info(
        "db.sql.plan_and_run_sql.steps_overview db_name=%s session_id=%s steps=%s",
        db_name,
        request.session_id,
        steps_summary,
    )

    sql_from_steps = _extract_sql_from_steps(agent_result)
    if not sql_from_steps:
        _LOGGER.error(
            "db.sql.plan_and_run_sql.no_sql_extracted db_name=%s session_id=%s",
            db_name,
            request.session_id,
        )
        raise RuntimeError("SQL Agent 未产生可解析的 SQL 查询")

    sql = sql_from_steps.strip()
    if not sql:
        _LOGGER.error(
            "db.sql.plan_and_run_sql.empty_sql db_name=%s session_id=%s",
            db_name,
            request.session_id,
        )
        raise RuntimeError("SQL Agent 返回的 SQL 为空")

    result = run_sql_query(db=db, sql=sql, max_rows=max_rows, db_name=db_name)
    _LOGGER.info(
        "db.sql.plan_and_run_sql.done db_name=%s session_id=%s rows=%d columns=%d sql=%s",
        db_name,
        request.session_id,
        len(result.rows),
        len(result.columns),
        sql,
    )
    return [result]
