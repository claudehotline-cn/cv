FROM python:3.11-slim

WORKDIR /workspace

# Install system deps (for compilation if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Pre-install robust set of dependencies for Agents
RUN pip install --no-cache-dir \
    pytest \
    pytest-recording \
    pytest-asyncio \
    pydantic-settings \
    agentevals \
    langchain-core \
    langgraph \
    langchain-openai \
    langchain-ollama \
    langchain-anthropic \
    langchain-community \
    pymysql \
    pandas \
    openpyxl \
    matplotlib \
    tabulate \
    sqlalchemy \
    wcmatch

# We will mount the source code at runtime to /workspace
# This allows using local code changes without rebuilding
# But we need to install the package interactively or set PYTHONPATH

ENV PYTHONPATH=/workspace/agent-core:/workspace/agent-test:/workspace/agent-plugins:/workspace:/workspace/third-party/deepagents-0.3.0

CMD ["bash"]
