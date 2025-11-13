FROM python:3.10-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# 1) 先仅拷贝依赖清单，利用 Docker 层缓存避免代码改动导致重复安装
COPY model-trainer/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r /tmp/requirements.txt
# 2) 大包（torch/torchvision）单独一层，最大化缓存命中
RUN python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision --extra-index-url https://pypi.org/simple
# 3) 最后拷贝代码，避免触发上层依赖安装
COPY model-trainer /app/model-trainer

ENV PYTHONPATH=/app/model-trainer:$PYTHONPATH
EXPOSE 8088
ENTRYPOINT ["python","-m","model_trainer.trainer_service"]
