#!/usr/bin/env bash
set -euo pipefail

# Start MLflow tracking server (dev): MySQL backend (host) + local FS artifacts
# Usage: tools/mlflow/start_dev.sh [PORT]

PORT="${1:-5500}"
BACKEND_URI="mysql+pymysql://root:123456@127.0.0.1:13306/mlflow"
ART_ROOT="$(pwd)/logs/mlruns"
mkdir -p "$ART_ROOT"

echo "[mlflow] backend=$BACKEND_URI artifact=file:$ART_ROOT port=$PORT"
python3 -m pip install --user --upgrade mlflow pymysql >/dev/null 2>&1 || true
mlflow server \
  --backend-store-uri "$BACKEND_URI" \
  --default-artifact-root "file:$ART_ROOT" \
  --host 0.0.0.0 \
  --port "$PORT"

