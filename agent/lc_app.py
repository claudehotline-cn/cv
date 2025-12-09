from __future__ import annotations

"""
基于 LangServe 暴露 DB/Excel 图表 Agent 的最小应用。

用途：
- 在已有 Docker agent 容器内，配合 langchain CLI 使用：
  - langchain serve agent.lc_app:app
  - langchain app docker --module agent.lc_app:app  （根据 langchain CLI 版本调整）
"""

from fastapi import FastAPI
from langserve import add_routes
from langchain_core.runnables import RunnableLambda

from cv_agent.db.schema import DbAnalysisRequest, DbAgentResponse  # type: ignore[import]
from cv_agent.db.graph import invoke_db_chart_agent  # type: ignore[import]
from cv_agent.excel.schema import ExcelAnalysisRequest, ExcelAgentResponse  # type: ignore[import]
from cv_agent.excel.graph import invoke_excel_chart_agent  # type: ignore[import]


app = FastAPI(
    title="CV LangChain Agent (DB/Excel)",
    version="0.1.0",
    description="基于 LangGraph 的 DB/Excel 图表 Agent，通过 LangServe 暴露为 LangChain 项目。",
)


def _run_db_chart(input_dict: dict) -> dict:
    """将原有 DbAnalysisRequest/DbAgentResponse 适配为 LangServe 的 Runnable 接口。"""

    request = DbAnalysisRequest(**input_dict)
    response = invoke_db_chart_agent(request=request)
    return response.model_dump()


def _run_excel_chart(input_dict: dict) -> dict:
    """将原有 ExcelAnalysisRequest/ExcelAgentResponse 适配为 LangServe 的 Runnable 接口。"""

    request = ExcelAnalysisRequest(**input_dict)
    response = invoke_excel_chart_agent(request=request)
    return response.model_dump()


db_chart_runnable = RunnableLambda(_run_db_chart)
excel_chart_runnable = RunnableLambda(_run_excel_chart)


# 通过 LangServe 将两个 Runnable 暴露为 HTTP 接口。
add_routes(
    app,
    db_chart_runnable,
    path="/db/chart",
    input_type=DbAnalysisRequest,
    output_type=DbAgentResponse,
)

add_routes(
    app,
    excel_chart_runnable,
    path="/excel/chart",
    input_type=ExcelAnalysisRequest,
    output_type=ExcelAgentResponse,
)


if __name__ == "__main__":
    # 便于在容器内直接本地调试：
    # python -m agent.lc_app
    import uvicorn

    uvicorn.run("agent.lc_app:app", host="0.0.0.0", port=8100, reload=False)

