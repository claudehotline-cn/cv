# RAG Service Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY rag_service/requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY rag_service/rag_service ./rag_service

# 环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE 8200

# 启动命令
CMD ["uvicorn", "rag_service.main:app", "--host", "0.0.0.0", "--port", "8200"]
