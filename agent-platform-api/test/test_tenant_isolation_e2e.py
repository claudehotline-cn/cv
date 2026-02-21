import os
import asyncio
import uuid

import asyncpg
import requests


API_BASE_URL = os.getenv("E2E_API_BASE", "http://agent-api:8000")
AUTH_BASE_URL = os.getenv("E2E_AUTH_BASE", "http://agent-auth:8000")
ADMIN_EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@cv.example.com")
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "12345678")


def _headers(token: str, tenant_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
    }


def _provision_membership(user_id: str, tenant_id: str, role: str = "member") -> None:
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


def _login(email: str, password: str) -> str:
    login = requests.post(
        f"{API_BASE_URL}/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert login.status_code == 200, login.text
    data = login.json()
    token = data.get("access_token")
    assert token, data
    return token


def test_cross_tenant_isolation_for_sessions_and_tasks() -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    token = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    user_id = _current_user_id(token)

    _provision_membership(user_id, tenant_a, role="owner")
    _provision_membership(user_id, tenant_b, role="owner")

    headers_a = _headers(token, tenant_a)
    headers_b = _headers(token, tenant_b)

    create_a = requests.post(f"{API_BASE_URL}/sessions/", headers=headers_a, json={"title": "tenant-a-session"}, timeout=30)
    assert create_a.status_code == 200, create_a.text
    session_a = create_a.json()["id"]

    create_b = requests.post(f"{API_BASE_URL}/sessions/", headers=headers_b, json={"title": "tenant-b-session"}, timeout=30)
    assert create_b.status_code == 200, create_b.text
    session_b = create_b.json()["id"]

    list_a = requests.get(f"{API_BASE_URL}/sessions/", headers=headers_a, timeout=30)
    assert list_a.status_code == 200, list_a.text
    a_ids = {s["id"] for s in list_a.json().get("sessions", [])}
    assert session_a in a_ids
    assert session_b not in a_ids

    list_b = requests.get(f"{API_BASE_URL}/sessions/", headers=headers_b, timeout=30)
    assert list_b.status_code == 200, list_b.text
    b_ids = {s["id"] for s in list_b.json().get("sessions", [])}
    assert session_b in b_ids
    assert session_a not in b_ids

    cross_get_1 = requests.get(f"{API_BASE_URL}/sessions/{session_b}", headers=headers_a, timeout=30)
    cross_get_2 = requests.get(f"{API_BASE_URL}/sessions/{session_a}", headers=headers_b, timeout=30)
    assert cross_get_1.status_code == 404, cross_get_1.text
    assert cross_get_2.status_code == 404, cross_get_2.text

    cross_task_list = requests.get(f"{API_BASE_URL}/tasks/sessions/{session_b}", headers=headers_a, timeout=30)
    assert cross_task_list.status_code == 404, cross_task_list.text
