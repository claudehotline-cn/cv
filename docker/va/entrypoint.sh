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

VA_TRITON_EXTERNAL=${VA_TRITON_EXTERNAL:-1}
if [ "${VA_TRITON_EXTERNAL}" != "0" ]; then
  echo "[entrypoint] starting tritonserver..."
  "/opt/tritonserver/bin/tritonserver" \
    --model-repository="${TRITON_MODEL_REPO}" \
    --http-port="${TRITON_HTTP_PORT}" \
    --grpc-port="${TRITON_GRPC_PORT}" \
    --metrics-port="${TRITON_METRICS_PORT}" \
    --log-info=1 --log-verbose=0 &
  TRITON_PID=$!

  # Wait for Triton HTTP health ready (max 120s)
  READY_TIMEOUT=${VA_WAIT_TRITON_READY_TIMEOUT:-120}
  echo "[entrypoint] waiting Triton ready on http://127.0.0.1:${TRITON_HTTP_PORT}/v2/health/ready (timeout=${READY_TIMEOUT}s)"
  for i in $(seq 1 ${READY_TIMEOUT}); do
    code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${TRITON_HTTP_PORT}/v2/health/ready || true)
    if [ "${code}" = "200" ]; then
      echo "[entrypoint] Triton is ready (http 200)"
      break
    fi
    if ! kill -0 ${TRITON_PID} 2>/dev/null; then
      echo "[entrypoint] Triton process exited unexpectedly" >&2
      wait ${TRITON_PID} || true
      exit 1
    fi
    sleep 1
  done
else
  echo "[entrypoint] VA_TRITON_EXTERNAL=0, skip starting external tritonserver (in-process mode expected)"
  TRITON_PID=""
fi


echo "[entrypoint] starting VideoAnalyzer..."
/app/bin/VideoAnalyzer /app/config &
VA_PID=$!

term() {
  kill -TERM ${VA_PID} 2>/dev/null || true
  if [ -n "${TRITON_PID}" ]; then
    kill -TERM ${TRITON_PID} 2>/dev/null || true
  fi
  wait ${VA_PID} 2>/dev/null || true
  if [ -n "${TRITON_PID}" ]; then
    wait ${TRITON_PID} 2>/dev/null || true
  fi
}
trap term SIGINT SIGTERM EXIT

if [ -n "${TRITON_PID}" ]; then
  wait -n ${VA_PID} ${TRITON_PID}
else
  wait ${VA_PID}
fi
