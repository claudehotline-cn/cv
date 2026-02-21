# LangGraph-based DB/Excel chart agent (no hand-written FastAPI)

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY agent-langchain/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY agent-langchain /app/agent-langchain

EXPOSE 8100

# 通过 langgraph CLI 启动 Graph 服务与 Studio：
# - 使用 agent-langchain/langgraph.json 中定义的 db_chart/excel_chart 图；
# - 监听 0.0.0.0:8100 以便 compose 暴露。
CMD ["langgraph", "dev", "--config", "agent-langchain/langgraph.json", "--host", "0.0.0.0", "--port", "8100"]

