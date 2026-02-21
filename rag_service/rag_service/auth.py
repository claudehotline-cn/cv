import httpx
from fastapi import HTTPException, Request

from .config import settings


async def resolve_auth_context(request: Request) -> dict:
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authentication required")

    introspect_url = settings.auth_introspection_url
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(introspect_url, headers={"Authorization": auth_header})
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Auth service unavailable") from exc

    if resp.status_code >= 400:
        raise HTTPException(status_code=401, detail="Invalid token")

    data = resp.json()
    if not data.get("active"):
        raise HTTPException(status_code=401, detail="Inactive token")

    user_id = str(data.get("sub") or "").strip()
    role = str(data.get("role") or "user").strip().lower() or "user"
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid principal")
    return {"user_id": user_id, "role": role, "email": data.get("email")}


async def require_authenticated(request: Request) -> dict:
    return await resolve_auth_context(request)


async def require_admin(request: Request) -> dict:
    ctx = await resolve_auth_context(request)
    if ctx.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return ctx
