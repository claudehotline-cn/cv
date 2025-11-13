# syntax=docker/dockerfile:1.6
FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 预装 MLflow 及其常用后端驱动，利用 BuildKit 缓存加速重复构建
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip && \
    pip install mlflow pymysql boto3

EXPOSE 5500

# 运行命令由 Compose 提供（读取环境变量拼接后端与存储），此处不设置 ENTRYPOINT
