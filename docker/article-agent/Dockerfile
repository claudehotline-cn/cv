# syntax=docker/dockerfile:1.4

# LangGraph-based content article agent (no hand-written FastAPI)

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY article_agent/requirements.txt /app/requirements.txt

# 利用 BuildKit 的缓存挂载，加速多次构建时的 pip 安装：
# - 依赖列表不变时，该层会命中 Docker 层缓存；
# - 即便 requirements 变更，pip 自身缓存也会通过 /root/.cache/pip 复用。
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements.txt

COPY article_agent /app/article_agent

EXPOSE 8130

# 通过 langgraph CLI 启动内容整理 Graph 服务与 Studio：
# - 使用 article_agent/langgraph.json 中定义的 content-deep-agent / content-chat-agent 图；
# - 监听 0.0.0.0:8130 以便 compose 暴露。
CMD ["langgraph", "dev", "--config", "article_agent/langgraph.json", "--host", "0.0.0.0", "--port", "8130"]
