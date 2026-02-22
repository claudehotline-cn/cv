import os
import asyncio
import uuid

import asyncpg
import requests


API_BASE_URL = os.getenv("E2E_API_BASE", "http://agent-api:8000")
ADMIN_EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@cv.example.com")
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "12345678")


def _login_admin() -> str:
    r = requests.post(
        f"{API_BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    token = r.json().get("access_token")
    assert token
    return token


def _headers(token: str, tenant_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
    }


def _current_user_id(token: str) -> str:
    r = requests.get(
        f"{API_BASE_URL}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    uid = r.json().get("id")
    assert uid
    return uid


def _provision_membership(user_id: str, tenant_id: str, role: str = "owner") -> None:
    async def _run() -> None:
        conn = await asyncpg.connect(
            host=os.getenv("E2E_PG_HOST", "pgvector"),
            port=int(os.getenv("E2E_PG_PORT", "5432")),
            user=os.getenv("E2E_PG_USER", "cv_kb"),
            password=os.getenv("E2E_PG_PASSWORD", "cv_kb_pass"),
            database=os.getenv("E2E_PG_DB", "cv_kb"),
        )
        try:
            await conn.execute(
                """
                INSERT INTO tenants(id, name, status)
                VALUES($1::uuid, $2, 'active')
                ON CONFLICT (id) DO NOTHING
                """,
                tenant_id,
                f"tenant-{tenant_id[:8]}",
            )
            await conn.execute(
                """
                INSERT INTO tenant_memberships(id, tenant_id, user_id, role, status)
                VALUES(gen_random_uuid(), $1::uuid, $2, $3, 'active')
                ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = EXCLUDED.role, status='active'
                """,
                tenant_id,
                user_id,
                role,
            )
        finally:
            await conn.close()

    asyncio.run(_run())


def test_secrets_crud_rotate_and_status_e2e() -> None:
    token = _login_admin()
    user_id = _current_user_id(token)
    tenant_id = str(uuid.uuid4())
    _provision_membership(user_id, tenant_id, role="owner")
    h = _headers(token, tenant_id)

    create = requests.post(
        f"{API_BASE_URL}/secrets/",
        headers=h,
        json={"name": "openai_api_key", "value": "sk-test-123", "scope": "user", "provider": "openai"},
        timeout=30,
    )
    assert create.status_code == 200, create.text
    secret_id = create.json()["id"]

    listed = requests.get(f"{API_BASE_URL}/secrets/", headers=h, timeout=30)
    assert listed.status_code == 200, listed.text
    items = listed.json().get("items", [])
    assert any(item.get("id") == secret_id for item in items)

    detail = requests.get(f"{API_BASE_URL}/secrets/{secret_id}", headers=h, timeout=30)
    assert detail.status_code == 200, detail.text
    assert "value" not in detail.json()

    rotate = requests.post(
        f"{API_BASE_URL}/secrets/{secret_id}/rotate",
        headers=h,
        json={"value": "sk-test-456"},
        timeout=30,
    )
    assert rotate.status_code == 200, rotate.text
    assert int(rotate.json()["current_version"]) == 2

    disable = requests.post(f"{API_BASE_URL}/secrets/{secret_id}/disable", headers=h, timeout=30)
    assert disable.status_code == 200, disable.text
    assert disable.json()["status"] == "disabled"

    enable = requests.post(f"{API_BASE_URL}/secrets/{secret_id}/enable", headers=h, timeout=30)
    assert enable.status_code == 200, enable.text
    assert enable.json()["status"] == "active"

    deleted = requests.delete(f"{API_BASE_URL}/secrets/{secret_id}", headers=h, timeout=30)
    # some backends may report not-found on idempotent soft delete path; both are acceptable
    assert deleted.status_code in (200, 404), deleted.text
    if deleted.status_code == 200:
        assert deleted.json()["status"] == "deleted"


def test_task_secret_injection_and_audit_redaction_e2e() -> None:
    token = _login_admin()
    user_id = _current_user_id(token)
    tenant_id = str(uuid.uuid4())
    _provision_membership(user_id, tenant_id, role="owner")
    h = _headers(token, tenant_id)

    create_secret = requests.post(
        f"{API_BASE_URL}/secrets/",
        headers=h,
        json={"name": "openai_api_key", "value": "sk-live-secret-xyz", "scope": "user", "provider": "openai"},
        timeout=30,
    )
    assert create_secret.status_code == 200, create_secret.text

    create_session = requests.post(
        f"{API_BASE_URL}/sessions/",
        headers=h,
        json={"title": "secret-injection"},
        timeout=30,
    )
    assert create_session.status_code == 200, create_session.text
    session_id = create_session.json()["id"]

    execute = requests.post(
        f"{API_BASE_URL}/tasks/sessions/{session_id}/execute",
        headers=h,
        json={
            "message": "hello",
            "secret_refs": ["openai_api_key"],
            "config": {"api_key": "SHOULD_BE_REDACTED", "nested": {"token": "LEAK_ME_NOT"}},
        },
        timeout=30,
    )
    assert execute.status_code == 200, execute.text

    # verify existing audit views do not leak provided sensitive fields in payload
    runs = requests.get(f"{API_BASE_URL}/audit/runs?limit=20", headers=h, timeout=30)
    assert runs.status_code == 200, runs.text
    body = runs.json()
    text = str(body)
    assert "SHOULD_BE_REDACTED" not in text
    assert "LEAK_ME_NOT" not in text
    assert "sk-live-secret-xyz" not in text
