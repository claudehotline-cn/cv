from fastapi import HTTPException, Request
from agent_auth_client import AuthClient

from .config import settings


async def resolve_auth_context(request: Request) -> dict:
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authentication required")

    introspect_url = settings.auth_introspection_url
    try:
        principal = await AuthClient(introspection_url=introspect_url).introspect(authorization=auth_header)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Auth service unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"user_id": principal.user_id, "role": principal.role, "email": principal.email}


async def require_authenticated(request: Request) -> dict:
    return await resolve_auth_context(request)


async def require_admin(request: Request) -> dict:
    ctx = await resolve_auth_context(request)
    if ctx.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return ctx
