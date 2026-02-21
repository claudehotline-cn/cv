import os

from fastapi import HTTPException, Request
from agent_auth_client import AuthClient

from .config import settings


async def resolve_auth_context(request: Request) -> dict:
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header:
        auth_mode = (os.getenv("AUTH_MODE") or "mixed").strip().lower()
        allow_dev_headers = (os.getenv("AUTH_ALLOW_DEV_HEADERS") or "true").strip().lower() in ("1", "true", "yes", "on")
        if auth_mode in ("dev", "mixed") and allow_dev_headers:
            user_id = (request.headers.get("X-User-Id") or "").strip()
            role = (request.headers.get("X-User-Role") or "user").strip().lower() or "user"
            tenant_id = (request.headers.get("X-Tenant-Id") or settings.auth_default_tenant_id or "").strip()
            tenant_role = (request.headers.get("X-Tenant-Role") or ("owner" if role == "admin" else "member")).strip().lower()
            if not user_id:
                raise HTTPException(status_code=401, detail="Authentication required")
            if role not in ("admin", "user"):
                role = "user"
            if tenant_role not in ("owner", "admin", "member"):
                tenant_role = "member"
            if not tenant_id:
                raise HTTPException(status_code=401, detail="Tenant context required")
            return {
                "user_id": user_id,
                "role": role,
                "email": None,
                "tenant_id": tenant_id,
                "tenant_role": tenant_role,
            }
        raise HTTPException(status_code=401, detail="Authentication required")

    introspect_url = settings.auth_introspection_url
    try:
        principal = await AuthClient(introspection_url=introspect_url).introspect(authorization=auth_header)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Auth service unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid token")
    tenant_id = (principal.tenant_id or settings.auth_default_tenant_id or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant context required")
    tenant_role = (principal.tenant_role or ("owner" if principal.role == "admin" else "member")).strip().lower()
    if tenant_role not in ("owner", "admin", "member"):
        tenant_role = "member"
    return {
        "user_id": principal.user_id,
        "role": principal.role,
        "email": principal.email,
        "tenant_id": tenant_id,
        "tenant_role": tenant_role,
    }


async def require_authenticated(request: Request) -> dict:
    return await resolve_auth_context(request)


async def require_admin(request: Request) -> dict:
    ctx = await resolve_auth_context(request)
    if ctx.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return ctx
