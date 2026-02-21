#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[agent-tests] Running agent-auth contract tests"
docker exec agent-auth python -m pytest -q --rootdir /app /app/app/tests/contract

echo "[agent-tests] Running plugin tests"
for dir in "$ROOT_DIR"/agent-plugins/*/; do
  if [ -d "$dir/tests" ]; then
    echo "Testing $dir"
    pytest -q "$dir/tests"
  fi
done

echo "[agent-tests] Done"
