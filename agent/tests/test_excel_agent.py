from __future__ import annotations

from typing import Any

import pytest
import pandas as pd

from cv_agent.excel.analysis import analyze_dataframe_for_chart
from cv_agent.excel.df_store import get_df_store
from cv_agent.excel.schema import ExcelAnalysisPlan, ExcelAnalysisRequest, ExcelChartPlan


def _build_sample_df() -> pd.DataFrame:
    """构造一个简单的月份-销售额-利润示例 DataFrame。"""

    return pd.DataFrame(
        {
            "month": ["2024-01", "2024-02", "2024-03"],
            "sales": [1000, 1500, 1800],
            "profit": [200, 260, 300],
        }
    )


def test_analyze_dataframe_for_chart_basic() -> None:
    """直接对 DataFrame 调用 analyze_dataframe_for_chart，应按月份聚合销售额与利润。"""

    df = _build_sample_df()
    store = get_df_store()
    df_id = store.put_df(session_id="s-analyze", file_id="f-analyze", sheet_name="Sheet1", df=df)

    plan = ExcelChartPlan(
        id="chart_1",
        group_by="month",
        metrics=["sales", "profit"],
        agg="sum",
        chart_type="line",
    )

    analyzed = analyze_dataframe_for_chart(df_id=df_id, plan=plan)

    # 维度应为 month，度量应包含 sales 和 profit
    assert analyzed.group_by == "month"
    assert "sales" in analyzed.metrics
    assert "profit" in analyzed.metrics
    assert analyzed.columns[0] == "month"
    assert len(analyzed.rows) == 3


class _DummySettingsExcel:
    """最小设置 stub，用于 Excel Agent LLM 测试。"""

    def __init__(self) -> None:
        self.llm_provider = "openai"
        self.openai_api_key = "dummy-key"
        self.llm_model = "dummy-model"
        self.request_timeout_sec = 5.0


class _DummyLLM:
    """替代真实 ChatOpenAI/Ollama 的 LLM stub。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        pass

    def invoke(self, prompt: str) -> Any:  # type: ignore[override]
        class _Result:
            def __init__(self, content: str) -> None:
                self.content = content

        # 根据 prompt 区分“分析计划 JSON”与“结论文本”两种调用场景。
        if "\"charts\"" in prompt and "\"group_by\"" in prompt and "\"metrics\"" in prompt:
            # 返回固定的分析计划 JSON，验证 plan LLM 链路。
            plan_json = (
                '{'
                '  "charts": ['
                '    {'
                '      "id": "chart_1",'
                '      "group_by": "month",'
                '      "metrics": ["sales", "profit"],'
                '      "agg": "sum",'
                '      "chart_type": "line"'
                '    }'
                '  ]'
                '}'
            )
            return _Result(plan_json)

        # 其余情况视为 insight 生成，返回固定结论文本。
        return _Result("这是基于示例数据生成的测试结论。")


@pytest.mark.asyncio
async def test_invoke_excel_chart_agent_uses_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端调用 invoke_excel_chart_agent，要求必须经过 LLM 生成 insight。"""

    from cv_agent.excel import graph as excel_graph_mod

    # 使用 Dummy 设置与 Dummy LLM，避免真实网络调用。
    monkeypatch.setattr(excel_graph_mod, "get_settings", lambda: _DummySettingsExcel(), raising=False)
    monkeypatch.setattr(excel_graph_mod, "ChatOpenAI", _DummyLLM, raising=False)
    monkeypatch.setattr(excel_graph_mod, "ChatOllama", _DummyLLM, raising=False)

    # 通过 DataFrameStore 准备一个虚拟 DataFrame，并 monkeypatch loader，避免文件 IO。
    df = _build_sample_df()
    store = get_df_store()
    df_id = store.put_df(session_id="s-e2e", file_id="excel_123", sheet_name="Sheet1", df=df)

    def _fake_load_excel_for_session(
        request: ExcelAnalysisRequest,
        max_preview_rows: int = 10,
    ) -> tuple[str, str, dict[str, Any]]:
        preview = {
            "columns": list(df.columns),
            "rows": df.head(max_preview_rows).to_dict(orient="records"),
        }
        return df_id, "Sheet1", preview

    monkeypatch.setattr(
        excel_graph_mod,
        "load_excel_for_session",
        _fake_load_excel_for_session,
        raising=False,
    )

    req = ExcelAnalysisRequest(
        session_id="s-e2e",
        file_id="excel_123",
        sheet_name=None,
        query="按月份统计销售额和利润，画一个双折线图，并给出结论",
    )

    # 通过 Agent 包装调用（内部会经过 LangGraph + LLM）。
    response = await excel_graph_mod.get_excel_graph().ainvoke({"request": req})  # type: ignore[call-arg]
    assert isinstance(response, dict)
    resp_obj = response.get("response")
    assert resp_obj is not None
    charts = resp_obj.charts  # type: ignore[union-attr]
    assert charts
    insight = resp_obj.insight  # type: ignore[union-attr]
    assert isinstance(insight, str)
    assert "测试结论" in insight
