from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.config import get_settings
from app.core.errors import AuthError
from app.infrastructure.wiring.container import Container
from app.api.deps import get_container


router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/introspect")
async def introspect(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    container: Container = Depends(get_container),
):
    try:
        svc = container.introspect_service()
        principal = await svc.execute(authorization, x_api_key=x_api_key)
        tenant = svc.tenant_context_for(principal)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {
        "active": True,
        "sub": principal.user_id,
        "email": principal.email,
        "role": principal.role,
        "tenant_id": tenant["tenant_id"],
        "tenant_role": tenant["tenant_role"],
    }


@router.get("/health/auth")
async def auth_health():
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name}
