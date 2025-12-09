from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import pymysql
from pymysql.cursors import DictCursor

from ..config import get_settings
from .schema import DbSchemaPreview, DbTablePreview

_LOGGER = logging.getLogger("agent_langchain.db")


def _get_db_connection(db_name: str) -> pymysql.connections.Connection:
    """根据配置创建到 MySQL 数据库的只读连接。"""

    settings = get_settings()

    host = getattr(settings, "db_host", "mysql")
    port = int(getattr(settings, "db_port", 3306))
    user = getattr(settings, "db_user", "root")
    password = getattr(settings, "db_password", "123456")

    _LOGGER.info(
        "db.loader.connect host=%s port=%d db=%s user=%s",
        host,
        port,
        db_name,
        user,
    )

    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db_name,
        cursorclass=DictCursor,
        autocommit=True,
    )
    return conn


def _list_candidate_tables(conn: pymysql.connections.Connection, db_name: str, max_tables: int = 8) -> List[str]:
    """从 information_schema 中列出候选表名。"""

    sql = """
    SELECT table_name AS table_name
    FROM information_schema.tables
    WHERE table_schema = %s
      AND table_type = 'BASE TABLE'
    ORDER BY table_name ASC
    LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (db_name, max_tables))
        rows = cur.fetchall()
    return [str(r["table_name"]) for r in rows]


def _get_table_columns(conn: pymysql.connections.Connection, db_name: str, table: str) -> List[str]:
    """获取表的列名列表。"""

    sql = """
    SELECT column_name AS column_name
    FROM information_schema.columns
    WHERE table_schema = %s AND table_name = %s
    ORDER BY ordinal_position ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (db_name, table))
        rows = cur.fetchall()
    return [str(r["column_name"]) for r in rows]


def _get_table_samples(
    conn: pymysql.connections.Connection,
    table: str,
    max_rows: int = 5,
) -> List[Dict[str, Any]]:
    """从表中抽取少量样本行。"""

    sql = f"SELECT * FROM `{table}` LIMIT %s"
    with conn.cursor() as cur:
        cur.execute(sql, (max_rows,))
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def load_schema_preview(db_name: str, max_tables: int = 8, max_rows: int = 5) -> DbSchemaPreview:
    """加载数据库 schema 预览及样本数据，供 LLM 决策使用。"""

    conn = _get_db_connection(db_name)
    try:
        tables = _list_candidate_tables(conn, db_name, max_tables=max_tables)
        previews: List[DbTablePreview] = []
        for t in tables:
            try:
                cols = _get_table_columns(conn, db_name, t)
                samples = _get_table_samples(conn, t, max_rows=max_rows)
                preview = DbTablePreview(name=t, columns=cols, sample_rows=samples)
                previews.append(preview)
            except Exception as exc:  # pragma: no cover
                _LOGGER.warning("db.loader.table_preview_failed table=%s error=%s", t, exc)
                continue
    finally:
        conn.close()

    schema = DbSchemaPreview(db_name=db_name, tables=previews)
    _LOGGER.info(
        "db.loader.schema_preview.done db=%s tables=%d",
        db_name,
        len(previews),
    )
    return schema


def execute_chart_query(
    db_name: str,
    table: str,
    group_by: str | None,
    metrics: List[str],
    agg: str,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """根据图表计划执行 SQL 聚合查询，返回列名与结果行列表。"""

    if agg not in ("sum", "count"):
        raise ValueError(f"不支持的聚合方式: {agg}")

    if not metrics:
        raise ValueError("metrics 不能为空")

    conn = _get_db_connection(db_name)
    try:
        cols: List[str] = []
        select_exprs: List[str] = []

        if group_by:
            cols.append(group_by)
            select_exprs.append(f"`{group_by}` AS `{group_by}`")

        for m in metrics:
            if agg == "sum":
                expr = f"SUM(`{m}`) AS `{m}`"
            else:
                expr = f"COUNT(`{m}`) AS `{m}`"
            select_exprs.append(expr)
            cols.append(m)

        select_sql = ", ".join(select_exprs)
        sql = f"SELECT {select_sql} FROM `{table}`"
        params: Tuple[Any, ...] = ()

        if group_by:
            sql += f" GROUP BY `{group_by}`"

        _LOGGER.info("db.loader.execute_chart_query sql=%s", sql)

        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]

        return cols, rows
    finally:
        conn.close()

