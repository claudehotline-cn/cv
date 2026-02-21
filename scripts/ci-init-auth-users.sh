#!/usr/bin/env bash
set -euo pipefail

API_URL="${E2E_API_BASE:-http://localhost:18111}"

ADMIN_EMAIL="${E2E_ADMIN_EMAIL:-admin@cv.example.com}"
ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-12345678}"
USER_A_EMAIL="${E2E_USER_A_EMAIL:-e2e_user_a@cv.example.com}"
USER_B_EMAIL="${E2E_USER_B_EMAIL:-e2e_user_b@cv.example.com}"
USER_PASSWORD="${E2E_USER_PASSWORD:-UserPass123!}"

echo "[ci-init] ensure e2e users via /auth/register"

register_user() {
  local email="$1"
  local password="$2"
  local username="$3"

  local code
  code=$(curl -s -o /tmp/ci_auth_register.out -w '%{http_code}' \
    -X POST "${API_URL}/auth/register" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"${email}\",\"password\":\"${password}\",\"username\":\"${username}\"}")

  # 200 created, 403 register disabled, 409 already exists
  if [[ "$code" != "200" && "$code" != "403" && "$code" != "409" ]]; then
    echo "[ci-init] register ${email} failed: code=${code}"
    cat /tmp/ci_auth_register.out || true
    exit 1
  fi
}

register_user "$USER_A_EMAIL" "$USER_PASSWORD" "e2e_user_a"
register_user "$USER_B_EMAIL" "$USER_PASSWORD" "e2e_user_b"

echo "[ci-init] verify admin login"
curl -fsS -X POST "${API_URL}/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" >/dev/null

echo "[ci-init] done"
