from dataclasses import dataclass

import httpx
from fastapi import Depends, HTTPException, Request

from agent_core.settings import get_settings


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: str
    role: str
    email: str | None = None


async def _introspect_bearer(token: str) -> AuthPrincipal:
    settings = get_settings()
    url = settings.auth_introspection_url
    if not url:
        raise HTTPException(status_code=500, detail="Auth introspection URL not configured")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers={"Authorization": f"Bearer {token}"})
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Auth service unavailable") from exc

    if resp.status_code >= 400:
        raise HTTPException(status_code=401, detail="Invalid token")

    data = resp.json()
    if not data.get("active"):
        raise HTTPException(status_code=401, detail="Inactive token")

    user_id = str(data.get("sub") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token principal")
    role = str(data.get("role") or "user").strip().lower() or "user"
    return AuthPrincipal(user_id=user_id, role=role, email=data.get("email"))


def _dev_header_principal(request: Request) -> AuthPrincipal:
    raw_user_id = (request.headers.get("X-User-Id") or "").strip()
    raw_role = (request.headers.get("X-User-Role") or "").strip().lower()
    if not raw_user_id and not raw_role:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_id = raw_user_id or "anonymous"
    role = raw_role or "user"
    if role not in ("admin", "user"):
        role = "user"
    return AuthPrincipal(user_id=user_id, role=role)


async def get_current_user(request: Request) -> AuthPrincipal:
    settings = get_settings()
    mode = settings.auth_mode

    auth_header = request.headers.get("Authorization") or ""
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            raise HTTPException(status_code=401, detail="Empty bearer token")
        return await _introspect_bearer(token)

    if mode in ("dev", "mixed") and settings.auth_allow_dev_headers:
        return _dev_header_principal(request)

    raise HTTPException(status_code=401, detail="Authentication required")


async def require_admin(user: AuthPrincipal = Depends(get_current_user)) -> AuthPrincipal:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
