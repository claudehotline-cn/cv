# Agent service (FastAPI + LangChain/LangGraph)

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY agent /app/agent

# Create non-root user
RUN useradd -m -u 10001 appuser
USER appuser

EXPOSE 8000

ENV AGENT_LOG_LEVEL=INFO

CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

