# syntax=docker/dockerfile:1.6
FROM python:3.10-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# 1) 先仅拷贝依赖清单，利用层缓存（再配合 BuildKit cache mount）
COPY model-trainer/requirements.torch.txt /tmp/requirements.torch.txt
COPY model-trainer/requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip && \
    pip install --index-url https://download.pytorch.org/whl/cpu \
      -r /tmp/requirements.torch.txt --extra-index-url https://pypi.org/simple && \
    pip install -r /tmp/requirements.txt

# 2) 最后拷贝代码，避免触发上层依赖安装
COPY model-trainer /app/model-trainer

ENV PYTHONPATH=/app/model-trainer:$PYTHONPATH
EXPOSE 8088
# 以 uvicorn 启动 FastAPI 服务（确保模块路径正确）
ENTRYPOINT ["python","-m","uvicorn","trainer_service.server:app","--host","0.0.0.0","--port","8088"]
