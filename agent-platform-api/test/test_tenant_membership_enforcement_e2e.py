import os
import asyncio
import uuid

import asyncpg
import requests


API_BASE_URL = os.getenv("E2E_API_BASE", "http://agent-api:8000")


def _auth_headers(token: str, tenant_id: str) -> dict[str, str]:
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


def _login_admin() -> str:
    email = os.getenv("E2E_ADMIN_EMAIL", "admin@cv.example.com")
    password = os.getenv("E2E_ADMIN_PASSWORD", "12345678")
    resp = requests.post(
        f"{API_BASE_URL}/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert resp.status_code == 200, resp.text
    token = resp.json().get("access_token")
    assert token, resp.text
    return token


def test_tenant_switch_requires_membership_for_bearer_user() -> None:
    token = _login_admin()
    user_id = _current_user_id(token)

    joined_tenant = str(uuid.uuid4())
    not_joined_tenant = str(uuid.uuid4())

    joined_headers = _auth_headers(token, joined_tenant)
    blocked_headers = _auth_headers(token, not_joined_tenant)

    _provision_membership(user_id, joined_tenant, role="owner")

    ok_create = requests.post(
        f"{API_BASE_URL}/sessions/",
        headers=joined_headers,
        json={"title": "joined-tenant"},
        timeout=30,
    )
    assert ok_create.status_code == 200, ok_create.text

    blocked_create = requests.post(
        f"{API_BASE_URL}/sessions/",
        headers=blocked_headers,
        json={"title": "not-joined-tenant"},
        timeout=30,
    )
    assert blocked_create.status_code == 403, blocked_create.text

    blocked_task_list = requests.get(
        f"{API_BASE_URL}/tasks/sessions/{ok_create.json()['id']}",
        headers=blocked_headers,
        timeout=30,
    )
    assert blocked_task_list.status_code == 403, blocked_task_list.text


def test_auth_tenants_returns_real_memberships() -> None:
    token = _login_admin()
    user_id = _current_user_id(token)
    tenant_x = str(uuid.uuid4())
    tenant_y = str(uuid.uuid4())

    _provision_membership(user_id, tenant_x, role="owner")
    _provision_membership(user_id, tenant_y, role="member")

    hx = _auth_headers(token, tenant_x)
    hy = _auth_headers(token, tenant_y)

    resp_x = requests.get(f"{API_BASE_URL}/auth/tenants", headers=hx, timeout=30)
    assert resp_x.status_code == 200, resp_x.text
    ids_x = {item.get("id") for item in resp_x.json().get("items", [])}
    assert tenant_x in ids_x

    resp_y = requests.get(f"{API_BASE_URL}/auth/tenants", headers=hy, timeout=30)
    assert resp_y.status_code == 200, resp_y.text
    ids_y = {item.get("id") for item in resp_y.json().get("items", [])}
    assert tenant_y in ids_y
