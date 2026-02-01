FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y gcc libpq-dev git curl libcairo2-dev && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install dependencies (exclude local agent-core which will be mounted)
RUN sed -i '/agent-core/d' requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium)
# NOTE: downloading browsers can be flaky in some environments; keep it optional.
ARG INSTALL_PLAYWRIGHT_BROWSERS=0
RUN if [ "$INSTALL_PLAYWRIGHT_BROWSERS" = "1" ]; then playwright install --with-deps chromium; else echo "Skipping playwright browser install"; fi
# Copy app code
COPY . .

# Set PYTHONPATH to include reusable in-repo packages (mounted via volumes)
ENV PYTHONPATH=/app/agent-audit:/app/agent-core:/app/agent-plugins:/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
