import asyncio
import os
import uuid

import asyncpg
import requests


API_BASE_URL = os.getenv("E2E_API_BASE", "http://agent-api:8000")


def _auth_headers(token: str, tenant_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
    }


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


def _provision_user_with_membership(
    user_id: str,
    email: str,
    tenant_id: str,
    *,
    role: str = "member",
    active: bool = True,
) -> None:
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
                INSERT INTO platform_users(user_id, email, role)
                VALUES($1, $2, 'user')
                ON CONFLICT (user_id) DO UPDATE SET email = EXCLUDED.email
                """,
                user_id,
                email,
            )
            await conn.execute(
                """
                INSERT INTO tenant_memberships(id, tenant_id, user_id, role, status)
                VALUES(gen_random_uuid(), $1::uuid, $2, $3, $4)
                ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = EXCLUDED.role, status = EXCLUDED.status
                """,
                tenant_id,
                user_id,
                role,
                "active" if active else "inactive",
            )
        finally:
            await conn.close()

    asyncio.run(_run())


def test_tenant_members_crud_flow() -> None:
    token = _login_admin()
    admin_user_id = _current_user_id(token)
    tenant_id = str(uuid.uuid4())
    target_user_id = f"u-{uuid.uuid4().hex[:10]}"
    target_email = f"{target_user_id}@example.com"

    _provision_user_with_membership(admin_user_id, f"{admin_user_id}@example.com", tenant_id, role="owner", active=True)
    _provision_user_with_membership(target_user_id, target_email, tenant_id, role="member", active=False)

    headers = _auth_headers(token, tenant_id)

    invite_resp = requests.post(
        f"{API_BASE_URL}/auth/tenants/{tenant_id}/members/invite",
        headers=headers,
        json={"user_id": target_user_id, "role": "member"},
        timeout=30,
    )
    assert invite_resp.status_code == 200, invite_resp.text
    assert invite_resp.json().get("status") == "active"

    list_resp = requests.get(
        f"{API_BASE_URL}/auth/tenants/{tenant_id}/members",
        headers=headers,
        timeout=30,
    )
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json().get("items", [])
    by_user = {item.get("user_id"): item for item in items}
    assert target_user_id in by_user
    assert by_user[target_user_id].get("email") == target_email
    assert by_user[target_user_id].get("role") == "member"

    patch_resp = requests.patch(
        f"{API_BASE_URL}/auth/tenants/{tenant_id}/members/{target_user_id}",
        headers=headers,
        json={"role": "admin"},
        timeout=30,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json().get("role") == "admin"

    delete_resp = requests.delete(
        f"{API_BASE_URL}/auth/tenants/{tenant_id}/members/{target_user_id}",
        headers=headers,
        timeout=30,
    )
    assert delete_resp.status_code == 200, delete_resp.text
    assert delete_resp.json().get("removed") is True

    list_after_delete = requests.get(
        f"{API_BASE_URL}/auth/tenants/{tenant_id}/members",
        headers=headers,
        timeout=30,
    )
    assert list_after_delete.status_code == 200, list_after_delete.text
    after_items = {item.get("user_id"): item for item in list_after_delete.json().get("items", [])}
    assert after_items[target_user_id].get("status") == "inactive"


def test_tenant_members_manager_permission_enforced() -> None:
    token = _login_admin()
    admin_user_id = _current_user_id(token)
    tenant_id = str(uuid.uuid4())
    member_user_id = f"u-{uuid.uuid4().hex[:10]}"
    member_email = f"{member_user_id}@example.com"
    newcomer_user_id = f"u-{uuid.uuid4().hex[:10]}"
    newcomer_email = f"{newcomer_user_id}@example.com"

    _provision_user_with_membership(admin_user_id, f"{admin_user_id}@example.com", tenant_id, role="member", active=True)
    _provision_user_with_membership(member_user_id, member_email, tenant_id, role="member", active=True)
    _provision_user_with_membership(newcomer_user_id, newcomer_email, tenant_id, role="member", active=False)

    headers = _auth_headers(token, tenant_id)

    list_resp = requests.get(
        f"{API_BASE_URL}/auth/tenants/{tenant_id}/members",
        headers=headers,
        timeout=30,
    )
    assert list_resp.status_code == 200, list_resp.text

    invite_resp = requests.post(
        f"{API_BASE_URL}/auth/tenants/{tenant_id}/members/invite",
        headers=headers,
        json={"user_id": newcomer_user_id, "role": "member"},
        timeout=30,
    )
    assert invite_resp.status_code == 403, invite_resp.text

    patch_resp = requests.patch(
        f"{API_BASE_URL}/auth/tenants/{tenant_id}/members/{member_user_id}",
        headers=headers,
        json={"role": "admin"},
        timeout=30,
    )
    assert patch_resp.status_code == 403, patch_resp.text

    delete_resp = requests.delete(
        f"{API_BASE_URL}/auth/tenants/{tenant_id}/members/{member_user_id}",
        headers=headers,
        timeout=30,
    )
    assert delete_resp.status_code == 403, delete_resp.text
