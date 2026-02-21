from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from agent_auth_client import AuthClient
from agent_core.settings import get_settings


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: str
    role: str
    email: str | None = None
    tenant_id: str | None = None
    tenant_role: str | None = None


async def _introspect_bearer(token: str) -> AuthPrincipal:
    settings = get_settings()
    url = settings.auth_introspection_url
    if not url:
        raise HTTPException(status_code=500, detail="Auth introspection URL not configured")

    try:
        principal = await AuthClient(url).introspect(authorization=f"Bearer {token}")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Auth service unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid token")
    return AuthPrincipal(
        user_id=principal.user_id,
        role=principal.role,
        email=principal.email,
        tenant_id=principal.tenant_id,
        tenant_role=principal.tenant_role,
    )


def _dev_header_principal(request: Request) -> AuthPrincipal:
    raw_user_id = (request.headers.get("X-User-Id") or "").strip()
    raw_role = (request.headers.get("X-User-Role") or "").strip().lower()
    if not raw_user_id and not raw_role:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_id = raw_user_id or "anonymous"
    role = raw_role or "user"
    if role not in ("admin", "user"):
        role = "user"
    settings = get_settings()
    tenant_id = (request.headers.get("X-Tenant-Id") or settings.auth_default_tenant_id or "").strip() or settings.auth_default_tenant_id
    tenant_role = (request.headers.get("X-Tenant-Role") or ("owner" if role == "admin" else "member")).strip().lower()
    if tenant_role not in ("owner", "admin", "member"):
        tenant_role = "member"
    return AuthPrincipal(user_id=user_id, role=role, tenant_id=tenant_id, tenant_role=tenant_role)


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
