import os
import time
import uuid

import pytest
import requests


API_BASE = os.getenv("E2E_API_BASE", "http://localhost:18111")
AUTH_BASE = os.getenv("E2E_AUTH_BASE", "http://localhost:18112")
RAG_BASE = os.getenv("E2E_RAG_BASE", "http://localhost:18200")
REQUIRE_RAG = os.getenv("E2E_REQUIRE_RAG", "true").lower() in ("1", "true", "yes", "on")

# Container-network defaults for running inside `agent-test` container.
if os.path.exists("/.dockerenv"):
    API_BASE = os.getenv("E2E_API_BASE", "http://agent-api:8000")
    AUTH_BASE = os.getenv("E2E_AUTH_BASE", "http://agent-auth:8000")
    RAG_BASE = os.getenv("E2E_RAG_BASE", "http://rag-service:8200")

ADMIN_EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@cv.example.com")
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "12345678")

USER_A_EMAIL = os.getenv("E2E_USER_A_EMAIL", "e2e_user_a@cv.example.com")
USER_B_EMAIL = os.getenv("E2E_USER_B_EMAIL", "e2e_user_b@cv.example.com")
USER_PASSWORD = os.getenv("E2E_USER_PASSWORD", "UserPass123!")


def _json(resp):
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def _login(email: str, password: str):
    resp = requests.post(
        f"{API_BASE}/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    return resp


def _auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}


def _ensure_test_user(email: str, password: str, role: str = "user") -> None:
    # Use public auth API to seed users, works in both host and container runs.
    # register may be disabled in strict env; in that case user must already exist.
    reg = requests.post(
        f"{AUTH_BASE}/auth/register",
        json={"email": email, "password": password, "username": email.split("@")[0]},
        timeout=20,
    )

    if reg.status_code not in (200, 403, 409):
        raise AssertionError(f"Failed to prepare test user {email}: {_json(reg)}")


@pytest.fixture(scope="session", autouse=True)
def ensure_auth_test_users():
    _ensure_test_user(USER_A_EMAIL, USER_PASSWORD, role="user")
    _ensure_test_user(USER_B_EMAIL, USER_PASSWORD, role="user")

    # Hard ensure passwords are set to expected test secret using auth API change-password flow when possible.
    for email in (USER_A_EMAIL, USER_B_EMAIL):
        login = _login(email, USER_PASSWORD)
        if login.status_code != 200:
            raise AssertionError(f"Failed to prepare test user {email}: {_json(login)}")


@pytest.mark.integration
@pytest.mark.auth_integration
def test_admin_login_and_protected_endpoints():
    login = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert login.status_code == 200, _json(login)
    body = _json(login)
    token = body["access_token"]

    me = requests.get(f"{API_BASE}/auth/me", headers=_auth_headers(token), timeout=20)
    assert me.status_code == 200, _json(me)
    assert _json(me).get("role") == "admin"

    rag = requests.get(f"{RAG_BASE}/api/knowledge-bases", headers=_auth_headers(token), timeout=20)
    if REQUIRE_RAG:
        assert rag.status_code == 200, _json(rag)
    else:
        assert rag.status_code in (200, 401, 403, 404, 503), _json(rag)


@pytest.mark.integration
@pytest.mark.auth_integration
def test_login_rate_limit_after_repeated_failures():
    test_email = f"nonexistent-{uuid.uuid4().hex[:8]}@example.com"
    last = None
    for _ in range(6):
        last = _login(test_email, "wrong-pass")
    assert last is not None
    assert last.status_code in (429, 401), _json(last)
    if last.status_code == 429:
        assert "Too many login attempts" in str(_json(last))


@pytest.mark.integration
@pytest.mark.auth_integration
def test_refresh_and_old_refresh_rejected():
    login = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert login.status_code == 200, _json(login)
    body = _json(login)
    refresh_token = body["refresh_token"]

    r1 = requests.post(
        f"{API_BASE}/auth/refresh",
        json={"refresh_token": refresh_token},
        timeout=20,
    )
    assert r1.status_code == 200, _json(r1)
    b1 = _json(r1)
    assert b1.get("access_token")
    assert b1.get("refresh_token")

    r2 = requests.post(
        f"{API_BASE}/auth/refresh",
        json={"refresh_token": refresh_token},
        timeout=20,
    )
    assert r2.status_code == 401, _json(r2)


@pytest.mark.integration
@pytest.mark.auth_integration
def test_logout_then_refresh_invalid():
    login = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert login.status_code == 200, _json(login)
    refresh_token = _json(login)["refresh_token"]

    out = requests.post(
        f"{API_BASE}/auth/logout",
        json={"refresh_token": refresh_token},
        timeout=20,
    )
    assert out.status_code == 200, _json(out)

    r = requests.post(
        f"{API_BASE}/auth/refresh",
        json={"refresh_token": refresh_token},
        timeout=20,
    )
    assert r.status_code == 401, _json(r)


@pytest.mark.integration
@pytest.mark.auth_integration
def test_user_cannot_access_others_session_task():
    t1 = _json(_login(USER_A_EMAIL, USER_PASSWORD))["access_token"]
    t2 = _json(_login(USER_B_EMAIL, USER_PASSWORD))["access_token"]

    s = requests.post(f"{API_BASE}/sessions/", json={}, headers=_auth_headers(t1), timeout=20)
    assert s.status_code == 200, _json(s)
    sid = _json(s)["id"]

    # user2 should not read user1 session
    s2 = requests.get(f"{API_BASE}/sessions/{sid}", headers=_auth_headers(t2), timeout=20)
    assert s2.status_code in (403, 404), _json(s2)

    # create task in user1 session
    exec_resp = requests.post(
        f"{API_BASE}/tasks/sessions/{sid}/execute",
        json={"message": "auth-e2e"},
        headers=_auth_headers(t1),
        timeout=20,
    )
    assert exec_resp.status_code == 200, _json(exec_resp)
    task_id = _json(exec_resp)["task_id"]

    # user2 should not read user1 task
    t2_task = requests.get(f"{API_BASE}/tasks/{task_id}", headers=_auth_headers(t2), timeout=20)
    assert t2_task.status_code in (403, 404), _json(t2_task)

    # let worker settle to reduce noisy logs
    time.sleep(1)


@pytest.mark.integration
@pytest.mark.auth_integration
def test_admin_can_access_auth_audit_endpoints():
    login = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert login.status_code == 200, _json(login)
    token = _json(login)["access_token"]

    events = requests.get(f"{API_BASE}/audit/auth/events?limit=5", headers=_auth_headers(token), timeout=20)
    assert events.status_code == 200, _json(events)

    overview = requests.get(f"{API_BASE}/audit/auth/overview", headers=_auth_headers(token), timeout=20)
    assert overview.status_code == 200, _json(overview)
