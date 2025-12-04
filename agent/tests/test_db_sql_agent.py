from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, text as sa_text

from cv_agent.db.sql_agent import SqlQueryResult, run_sql_query


class _DummySQLDatabase:
    """最小的 SQLDatabase stub，仅提供 engine 属性以供 run_sql_query 使用。"""

    def __init__(self, engine: Any) -> None:
        self.engine = engine


def _build_dummy_db() -> _DummySQLDatabase:
    """构造一个基于 SQLite 的内存数据库，包含简单测试表。"""

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa_text("CREATE TABLE t (id INTEGER PRIMARY KEY, value INTEGER)"))
        conn.execute(sa_text("INSERT INTO t (value) VALUES (10), (20), (30)"))
    return _DummySQLDatabase(engine)


def test_run_sql_query_select_only() -> None:
    """run_sql_query 应能正确执行只读 SELECT 查询并返回列名与数据行。"""

    db = _build_dummy_db()
    result: SqlQueryResult = run_sql_query(
        db=db,  # type: ignore[arg-type]
        sql="SELECT id, value FROM t ORDER BY id",
        max_rows=10,
        db_name="test_db",
    )

    assert isinstance(result, SqlQueryResult)
    assert result.columns == ["id", "value"]
    assert len(result.rows) == 3
    assert result.rows[0][1] == 10


def test_run_sql_query_rejects_non_select() -> None:
    """非 SELECT/WHEN 开头的 SQL 应被安全检查拒绝。"""

    db = _build_dummy_db()
    with pytest.raises(ValueError):
        run_sql_query(
            db=db,  # type: ignore[arg-type]
            sql="DELETE FROM t WHERE id = 1",
            max_rows=10,
            db_name="test_db",
        )

