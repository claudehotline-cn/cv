from __future__ import annotations

from typing import Any, List

import pytest

from cv_agent.db import graph as db_graph_mod
from cv_agent.db.schema import DbAnalysisRequest, DbSchemaPreview, DbTablePreview
from cv_agent.db.sql_agent import SqlQueryResult


class _DummySettingsDb:
    """最小设置 stub，用于 DB Agent Graph 测试。"""

    def __init__(self) -> None:
        self.llm_provider = "openai"
        self.openai_api_key = "dummy-key"
        self.llm_model = "dummy-model"
        self.request_timeout_sec = 5.0
        self.db_default_name = "test_db"
        self.excel_max_chart_rows = 500


class _DummySQLDatabase:
    """最小 SQLDatabase stub，占位用，不实际访问数据库。"""

    def __init__(self) -> None:
        self.engine = None


def _build_fake_schema() -> DbSchemaPreview:
    """构造一个最小的 schema 预览对象。"""

    table = DbTablePreview(
        name="orders",
        columns=["month", "amount"],
        sample_rows=[{"month": "2024-01", "amount": 100}],
    )
    return DbSchemaPreview(db_name="test_db", tables=[table])


def test_invoke_db_chart_agent_uses_sql_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """调用 invoke_db_chart_agent 时，应通过 sql_agent.plan_and_run_sql 获取数据并返回 DbAgentResponse。"""

    # 使用 Dummy Settings，避免依赖真实环境变量。
    monkeypatch.setattr(db_graph_mod, "get_settings", lambda: _DummySettingsDb(), raising=False)

    # 避免真实 DB 访问与 loader 调用，仅返回固定 schema。
    fake_schema = _build_fake_schema()
    monkeypatch.setattr(db_graph_mod, "load_schema_preview", lambda db_name: fake_schema, raising=False)

    # 让 get_sql_database 返回占位对象，后续由 plan_and_run_sql stub 使用。
    dummy_sql_db = _DummySQLDatabase()
    monkeypatch.setattr(db_graph_mod, "get_sql_database", lambda db_name: dummy_sql_db, raising=False)

    # stub 掉 SQL Agent，直接返回固定聚合结果表。
    def _fake_plan_and_run_sql(
        request: DbAnalysisRequest,
        db: Any,
        db_name: str,
        max_rows: int = 500,
    ) -> List[SqlQueryResult]:
        assert db is dummy_sql_db
        assert db_name == "test_db"
        return [
            SqlQueryResult(
                sql="SELECT month, SUM(amount) AS total_amount FROM orders GROUP BY month",
                columns=["month", "total_amount"],
                rows=[["2024-01", 100], ["2024-02", 200]],
            )
        ]

    monkeypatch.setattr(db_graph_mod, "plan_and_run_sql", _fake_plan_and_run_sql, raising=False)

    # insight 生成同样使用 stub，避免真实 LLM 调用。
    monkeypatch.setattr(
        db_graph_mod,
        "_build_db_insight_text",
        lambda tables, request: "测试数据库分析结论",
        raising=False,
    )

    req = DbAnalysisRequest(
        session_id="s-db-e2e",
        query="按月份统计订单金额并画图",
        db_name="test_db",
    )

    state = db_graph_mod.get_db_graph().invoke({"request": req})  # type: ignore[call-arg]
    assert isinstance(state, dict)
    resp = state.get("response")
    assert resp is not None
    assert resp.used_db_name == "test_db"
    assert resp.charts
    assert isinstance(resp.insight, str)
    assert "数据库分析结论" in resp.insight

