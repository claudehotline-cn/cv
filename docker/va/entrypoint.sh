#!/usr/bin/env bash
set -euo pipefail

: "${TRITON_MODEL_REPO:=/models}"
: "${TRITON_HTTP_PORT:=8000}"
: "${TRITON_GRPC_PORT:=8001}"
: "${TRITON_METRICS_PORT:=8002}"

# 兼容 app.yaml 中使用 triton:8001 的配置，将 triton 映射到本地
if ! grep -qE "(^|\s)triton(\s|$)" /etc/hosts; then
  echo "127.0.0.1 triton" >> /etc/hosts || true
fi

mkdir -p "${TRITON_MODEL_REPO}"

echo "[entrypoint] starting tritonserver..."
/opt/tritonserver/bin/tritonserver \
  --model-repository="${TRITON_MODEL_REPO}" \
  --http-port="${TRITON_HTTP_PORT}" \
  --grpc-port="${TRITON_GRPC_PORT}" \
  --metrics-port="${TRITON_METRICS_PORT}" \
  --log-info=1 --log-verbose=0 &
TRITON_PID=$!

sleep 1

echo "[entrypoint] starting VideoAnalyzer..."
/app/bin/VideoAnalyzer /app/config &
VA_PID=$!

term() {
  kill -TERM ${VA_PID} 2>/dev/null || true
  kill -TERM ${TRITON_PID} 2>/dev/null || true
  wait ${VA_PID} 2>/dev/null || true
  wait ${TRITON_PID} 2>/dev/null || true
}
trap term SIGINT SIGTERM EXIT

wait -n ${VA_PID} ${TRITON_PID}
