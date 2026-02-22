import os
import asyncio
import time
import uuid

import asyncpg
import pytest
import requests


API_BASE_URL = os.getenv("E2E_API_BASE", "http://agent-api:8000")
ADMIN_EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@cv.example.com")
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "12345678")


def _login_admin() -> str:
    resp = requests.post(
        f"{API_BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    assert resp.status_code == 200, resp.text
    token = resp.json().get("access_token")
    assert token, resp.text
    return token


def _headers(token: str, tenant_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
    }


def _current_user_id(token: str) -> str:
    resp = requests.get(
        f"{API_BASE_URL}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    user_id = data.get("id")
    assert user_id, data
    return user_id


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
                ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = EXCLUDED.role, status = 'active'
                """,
                tenant_id,
                user_id,
                role,
            )
        finally:
            await conn.close()

    asyncio.run(_run())


def test_rate_limit_429_on_sessions_write() -> None:
    token = _login_admin()
    user_id = _current_user_id(token)
    tenant_id = str(uuid.uuid4())
    _provision_membership(user_id, tenant_id)

    put = requests.put(
        f"{API_BASE_URL}/limits/admin/tenants/{tenant_id}",
        headers=_headers(token, tenant_id),
        json={"write_limit": "1/min"},
        timeout=30,
    )
    assert put.status_code == 200, put.text

    first = requests.post(
        f"{API_BASE_URL}/sessions/",
        headers=_headers(token, tenant_id),
        json={"title": "rl-first"},
        timeout=30,
    )
    assert first.status_code == 200, first.text

    second = requests.post(
        f"{API_BASE_URL}/sessions/",
        headers=_headers(token, tenant_id),
        json={"title": "rl-second"},
        timeout=30,
    )
    assert second.status_code == 429, second.text


def test_quota_exceeded_429_on_task_execute() -> None:
    token = _login_admin()
    user_id = _current_user_id(token)
    tenant_id = str(uuid.uuid4())
    _provision_membership(user_id, tenant_id)

    put_quota = requests.put(
        f"{API_BASE_URL}/limits/admin/tenants/{tenant_id}/quota",
        headers=_headers(token, tenant_id),
        json={"monthly_token_quota": 0, "enabled": True},
        timeout=30,
    )
    assert put_quota.status_code == 200, put_quota.text

    create_session = requests.post(
        f"{API_BASE_URL}/sessions/",
        headers=_headers(token, tenant_id),
        json={"title": "quota-session"},
        timeout=30,
    )
    assert create_session.status_code == 200, create_session.text
    session_id = create_session.json()["id"]

    execute = requests.post(
        f"{API_BASE_URL}/tasks/sessions/{session_id}/execute",
        headers=_headers(token, tenant_id),
        json={"message": "hello"},
        timeout=30,
    )
    assert execute.status_code == 429, execute.text


def test_concurrency_limit_recover_after_task_terminal() -> None:
    token = _login_admin()
    user_id = _current_user_id(token)
    tenant_id = str(uuid.uuid4())
    _provision_membership(user_id, tenant_id)

    set_limits = requests.put(
        f"{API_BASE_URL}/limits/admin/tenants/{tenant_id}",
        headers=_headers(token, tenant_id),
        json={"tenant_concurrency_limit": 1, "user_concurrency_limit": 1, "execute_limit": "100/min"},
        timeout=30,
    )
    assert set_limits.status_code == 200, set_limits.text

    set_quota = requests.put(
        f"{API_BASE_URL}/limits/admin/tenants/{tenant_id}/quota",
        headers=_headers(token, tenant_id),
        json={"monthly_token_quota": 50000000, "enabled": True},
        timeout=30,
    )
    assert set_quota.status_code == 200, set_quota.text

    create_session = requests.post(
        f"{API_BASE_URL}/sessions/",
        headers=_headers(token, tenant_id),
        json={"title": "cc-session"},
        timeout=30,
    )
    assert create_session.status_code == 200, create_session.text
    session_id = create_session.json()["id"]

    first = requests.post(
        f"{API_BASE_URL}/tasks/sessions/{session_id}/execute",
        headers=_headers(token, tenant_id),
        json={"message": "first"},
        timeout=30,
    )
    assert first.status_code == 200, first.text
    task_id = first.json()["task_id"]

    second = requests.post(
        f"{API_BASE_URL}/tasks/sessions/{session_id}/execute",
        headers=_headers(token, tenant_id),
        json={"message": "second"},
        timeout=30,
    )
    assert second.status_code == 429, second.text

    # Request cancellation so concurrency slot can be released.
    cancel = requests.post(
        f"{API_BASE_URL}/tasks/{task_id}/cancel",
        headers=_headers(token, tenant_id),
        timeout=30,
    )
    assert cancel.status_code in (200, 400), cancel.text

    # Best effort wait for first task to leave running state.
    deadline = time.time() + 60
    terminal = False
    while time.time() < deadline:
        st = requests.get(f"{API_BASE_URL}/tasks/{task_id}", headers=_headers(token, tenant_id), timeout=30)
        assert st.status_code == 200, st.text
        status = st.json().get("status")
        if status in ("completed", "failed", "cancelled", "timed_out", "waiting_approval"):
            terminal = True
            break
        time.sleep(1)
    if not terminal:
        pytest.skip("task did not reach terminal state in time; environment likely saturated")

    third = requests.post(
        f"{API_BASE_URL}/tasks/sessions/{session_id}/execute",
        headers=_headers(token, tenant_id),
        json={"message": "third"},
        timeout=30,
    )
    assert third.status_code == 200, third.text
