FROM python:3.10-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY model-trainer /app/model-trainer
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r /app/model-trainer/requirements.txt && \
    python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision --extra-index-url https://pypi.org/simple

ENV PYTHONPATH=/app/model-trainer:$PYTHONPATH
EXPOSE 8088
ENTRYPOINT ["python","-m","model_trainer.trainer_service"]

