FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y gcc libpq-dev git curl && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install dependencies (exclude local agent-core which will be mounted)
RUN sed -i '/agent-core/d' requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Set PYTHONPATH to include agent-core and plugins (which are mounted via volumes)
ENV PYTHONPATH=/app/agent-core:/app/agent-plugins:/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
