# Agent Chat API Dockerfile
# 使用 FastAPI + uvicorn 运行自定义 API 服务

FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY agent-langchain/requirements.txt ./requirements.txt

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY agent-langchain/agent_langchain ./agent_langchain

# 创建数据目录
RUN mkdir -p /data/workspace /logs

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "agent_langchain.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
