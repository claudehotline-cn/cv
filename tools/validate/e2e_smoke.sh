#!/usr/bin/env bash
set -euo pipefail

CP_URL="http://127.0.0.1:8080"
TIMEOUT=3000

usage() {
  echo "Usage: $(basename "$0") --cp <http://host:port> [--timeout-ms <ms>]";
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cp) CP_URL="$2"; shift 2 ;;
    --timeout-ms) TIMEOUT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 2 ;;
  esac
done

fail() { echo "[FAIL] $1" >&2; exit 1; }
pass() { echo "[OK] $1"; }

curl_json() {
  local path="$1";
  curl -sS --max-time "$(( (TIMEOUT+999)/1000 ))" "$CP_URL$path"
}

# 1) Engine schema
resp=$(curl_json "/api/ui/schema/engine") || fail "schema request error"
echo "$resp" | python3 tools/validate/json_assert.py --expect data.title=EngineOptionsSchema || fail "schema invalid"
pass "/api/ui/schema/engine"

# 2) Metrics summary
resp=$(curl_json "/api/_metrics/summary") || fail "metrics summary request error"
echo "$resp" | python3 tools/validate/json_assert.py --expect data.cp.requests_total:int --expect data.cache.hits:int --expect data.cache.misses:int || fail "metrics summary invalid"
pass "/api/_metrics/summary"

# 3) VA runtime (best-effort)
resp=$(curl_json "/api/va/runtime") || { echo "[WARN] /api/va/runtime unavailable"; exit 0; }
echo "$resp" | python3 tools/validate/json_assert.py --expect data.provider --expect data.gpu_active:bool || { echo "[WARN] va/runtime invalid"; exit 0; }
pass "/api/va/runtime"

echo "[SUMMARY] E2E smoke passed on $CP_URL"

