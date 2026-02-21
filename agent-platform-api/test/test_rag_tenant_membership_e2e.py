import os
import asyncio
import uuid

import asyncpg
import requests


API_BASE_URL = os.getenv("E2E_API_BASE", "http://agent-api:8000")


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


def test_rag_requires_tenant_membership() -> None:
    token = _login_admin()
    user_id = _current_user_id(token)

    joined_tenant = str(uuid.uuid4())
    blocked_tenant = str(uuid.uuid4())
    _provision_membership(user_id, joined_tenant, role="owner")

    ok = requests.get(
        f"{API_BASE_URL}/rag/knowledge-bases",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": joined_tenant},
        timeout=30,
    )
    assert ok.status_code == 200, ok.text

    blocked = requests.get(
        f"{API_BASE_URL}/rag/knowledge-bases",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": blocked_tenant},
        timeout=30,
    )
    assert blocked.status_code == 403, blocked.text
