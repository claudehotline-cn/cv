#!/usr/bin/env bash
set -euo pipefail

API_URL="${E2E_API_BASE:-http://localhost:18111}"
AUTH_URL="${E2E_AUTH_BASE:-http://localhost:18112}"
RAG_URL="${E2E_RAG_BASE:-http://localhost:18200}"

wait_http() {
  local name="$1"
  local url="$2"
  local max_retries="${3:-60}"
  local sleep_sec="${4:-2}"

  echo "[ci-wait] waiting for ${name}: ${url}"
  local i
  for i in $(seq 1 "$max_retries"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[ci-wait] ${name} is ready"
      return 0
    fi
    sleep "$sleep_sec"
  done

  echo "[ci-wait] timeout waiting for ${name}: ${url}"
  return 1
}

wait_http "agent-auth" "${AUTH_URL}/health" 90 2
wait_http "agent-api" "${API_URL}/health" 90 2

# RAG health endpoint may vary; best-effort check using known path.
if ! wait_http "rag-service" "${RAG_URL}/health" 40 2; then
  echo "[ci-wait] rag-service health endpoint not ready, continue as optional"
fi
