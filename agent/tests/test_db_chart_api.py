from __future__ import annotations

import pytest

from cv_agent.db.schema import DbAnalysisRequest, DbAgentResponse
from cv_agent.excel.schema import ExcelChartResult
from cv_agent.server import api


@pytest.mark.asyncio
async def test_db_chart_endpoint_uses_invoke_db_chart_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 /v1/agent/db/chart Handler 会调用 invoke_db_chart_agent 并返回 DbAgentResponse。"""

    dummy_chart = ExcelChartResult(
        id="chart_1",
        title="测试图表",
        description="测试描述",
        option={"dataset": {"source": [["month", "amount"], ["2024-01", 100]]}},
    )
    dummy_response = DbAgentResponse(
        used_db_name="cv_cp",
        charts=[dummy_chart],
        insight="测试数据库分析结论",
    )

    called: dict[str, object] = {}

    def _fake_invoke_db_chart_agent(
        request: DbAnalysisRequest,
        user: dict | None = None,
    ) -> DbAgentResponse:
        called["request"] = request
        called["user"] = user or {}
        return dummy_response

    monkeypatch.setattr(api, "invoke_db_chart_agent", _fake_invoke_db_chart_agent, raising=False)

    req = DbAnalysisRequest(
        session_id="s-http",
        query="按月份统计订单金额和订单数，画一个双折线图",
        db_name="cv_cp",
    )
    user = api.UserContext(user_id="u-http", role="admin", tenant="tenant-http")

    response = await api.db_chart(req, user)  # type: ignore[arg-type]

    assert isinstance(response, DbAgentResponse)
    assert response.used_db_name == "cv_cp"
    assert response.charts and response.charts[0].id == "chart_1"
    assert isinstance(response.insight, str)
    # 验证 Handler 确实调用了 invoke_db_chart_agent 且透传了用户上下文
    called_req = called.get("request")
    assert isinstance(called_req, DbAnalysisRequest)
    assert called_req.session_id == "s-http"
    called_user = called.get("user")
    assert isinstance(called_user, dict)
    assert called_user.get("user_id") == "u-http"
    assert called_user.get("role") == "admin"
    assert called_user.get("tenant") == "tenant-http"

