"""数据库工具模块：提供 SQL 执行和 schema 预览功能。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List
from urllib.parse import quote_plus

import pymysql
from pymysql.cursors import DictCursor
from langchain_community.utilities import SQLDatabase
from sqlalchemy import text

from ..config import get_settings

_LOGGER = logging.getLogger("agent_langchain.utils.db")


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class SqlQueryResult:
    """SQL 查询结果结构。"""
    sql: str
    columns: List[str]
    rows: List[List[Any]]


@dataclass
class DbTablePreview:
    """单张表的预览信息。"""
    name: str
    columns: List[str]
    sample_rows: List[Dict[str, Any]]


@dataclass
class DbSchemaPreview:
    """数据库 schema 预览。"""
    db_name: str
    tables: List[DbTablePreview]


# ============================================================================
# 数据库连接
# ============================================================================

def get_sql_database(db_name: str) -> SQLDatabase:
    """基于 Settings 构造 LangChain SQLDatabase 对象。"""
    settings = get_settings()
    host = getattr(settings, "db_host", "mysql")
    port = int(getattr(settings, "db_port", 3306))
    user = getattr(settings, "db_user", "root")
    password = getattr(settings, "db_password", "123456")

    safe_password = quote_plus(password)
    uri = f"mysql+pymysql://{user}:{safe_password}@{host}:{port}/{db_name}?charset=utf8mb4"

    _LOGGER.info("db_utils.get_sql_database uri=%s", uri.replace(safe_password, "***"))
    return SQLDatabase.from_uri(uri)


def _get_db_connection(db_name: str) -> pymysql.connections.Connection:
    """根据配置创建到 MySQL 数据库的只读连接。"""
    settings = get_settings()
    host = getattr(settings, "db_host", "mysql")
    port = int(getattr(settings, "db_port", 3306))
    user = getattr(settings, "db_user", "root")
    password = getattr(settings, "db_password", "123456")

    _LOGGER.info("db_utils.connect host=%s port=%d db=%s", host, port, db_name)
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db_name,
        cursorclass=DictCursor,
        autocommit=True,
        charset="utf8mb4",  # 必须强制使用 utf8mb4
    )


# ============================================================================
# SQL 执行
# ============================================================================

def _ensure_safe_select_sql(sql: str) -> str:
    """对 SQL 做最小安全校验，仅允许只读查询。"""
    stripped = sql.strip().strip(";")
    lowered = stripped.lower()
    
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError(f"仅允许 SELECT/WITH 查询，当前 SQL 为: {sql!r}")

    forbidden_keywords = (
        "insert ", "update ", "delete ", "drop ", "truncate ",
        "alter ", "create ", "merge ", "grant ", "revoke ",
    )
    for kw in forbidden_keywords:
        if kw in lowered:
            raise ValueError(f"SQL 中包含禁止关键字 {kw.strip()}: {sql!r}")

    # 结构校验：SELECT 必须包含 FROM
    if lowered.startswith("select"):
        normalized = " " + " ".join(lowered.split()) + " "
        if " from " not in normalized:
            raise ValueError(f"SQL 结构不完整，缺少 FROM 子句: {sql!r}")

    # WITH 必须包含 SELECT 和 FROM
    if lowered.startswith("with"):
        normalized = " " + " ".join(lowered.split()) + " "
        if " select " not in normalized or " from " not in normalized:
            raise ValueError(f"CTE SQL 结构不完整: {sql!r}")

    return stripped


def run_sql_query(
    db: SQLDatabase,
    sql: str,
    max_rows: int = 500,
    db_name: str | None = None,
) -> SqlQueryResult:
    """执行只读 SQL 查询，返回结构化结果。"""
    if max_rows <= 0:
        max_rows = 500
        
    safe_sql = _ensure_safe_select_sql(sql)

    engine = getattr(db, "engine", None) or getattr(db, "_engine", None)
    if engine is None:
        raise RuntimeError("SQLDatabase 缺少 engine 属性")

    import time
    start_ts = time.perf_counter()
    _LOGGER.info("db_utils.run_sql start sql=%s", safe_sql[:100])

    columns: List[str] = []
    rows: List[List[Any]] = []

    with engine.connect() as conn:
        # 尝试禁用 ONLY_FULL_GROUP_BY
        try:
            conn.execute(
                text("SET SESSION sql_mode=(SELECT REPLACE(@@sql_mode,'ONLY_FULL_GROUP_BY',''))")
            )
        except Exception:
            pass

        result = conn.execute(text(safe_sql))
        try:
            columns = list(result.keys())
        except Exception:
            cursor = result.cursor
            columns = [c[0] for c in cursor.description]

        for idx, row in enumerate(result):
            if idx >= max_rows:
                break
            try:
                row_data = [row[col] for col in columns]
            except Exception:
                row_data = list(row)
            rows.append(row_data)

    duration_ms = (time.perf_counter() - start_ts) * 1000.0
    _LOGGER.info("db_utils.run_sql done rows=%d duration_ms=%.1f", len(rows), duration_ms)
    return SqlQueryResult(sql=safe_sql, columns=columns, rows=rows)


# ============================================================================
# Schema 预览
# ============================================================================

def _list_candidate_tables(conn: pymysql.connections.Connection, db_name: str, max_tables: int = 8) -> List[str]:
    """列出候选表名。"""
    sql = """
    SELECT table_name AS table_name
    FROM information_schema.tables
    WHERE table_schema = %s AND table_type = 'BASE TABLE'
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


def _get_table_samples(conn: pymysql.connections.Connection, table: str, max_rows: int = 5) -> List[Dict[str, Any]]:
    """从表中抽取少量样本行。"""
    sql = f"SELECT * FROM `{table}` LIMIT %s"
    with conn.cursor() as cur:
        cur.execute(sql, (max_rows,))
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def load_schema_preview(db_name: str, max_tables: int = 8, max_rows: int = 5) -> DbSchemaPreview:
    """加载数据库 schema 预览及样本数据。"""
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
            except Exception as exc:
                _LOGGER.warning("db_utils.table_preview_failed table=%s error=%s", t, exc)
                continue
    finally:
        conn.close()

    schema = DbSchemaPreview(db_name=db_name, tables=previews)
    _LOGGER.info("db_utils.schema_preview done db=%s tables=%d", db_name, len(previews))
    return schema
