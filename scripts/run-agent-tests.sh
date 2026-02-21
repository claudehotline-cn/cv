#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[agent-tests] Running agent-auth contract tests"
docker exec agent-auth python -m pytest -q --rootdir /app /app/app/tests/contract

echo "[agent-tests] Running auth integration tests in agent-test container"
docker exec agent-test pytest -q -c /workspace/agent-test/pytest.ini -m auth_integration /workspace/agent-test/tests/integration/auth/test_auth_e2e.py

echo "[agent-tests] Running plugin tests"
for dir in "$ROOT_DIR"/agent-plugins/*/; do
  if [ -d "$dir/tests" ]; then
    echo "Testing $dir"
    PYTHONPATH="$ROOT_DIR/agent-core:$ROOT_DIR/agent-test:$ROOT_DIR/agent-plugins:$ROOT_DIR" \
      pytest -q "$dir/tests"
  fi
done

echo "[agent-tests] Done"
