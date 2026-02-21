from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.config import get_settings
from app.core.errors import AuthError
from app.infrastructure.wiring.container import Container
from app.api.deps import get_container


router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/introspect")
async def introspect(
    authorization: str | None = Header(default=None),
    container: Container = Depends(get_container),
):
    try:
        principal = container.introspect_service().execute(authorization)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {
        "active": True,
        "sub": principal.user_id,
        "email": principal.email,
        "role": principal.role,
    }


@router.get("/health/auth")
async def auth_health():
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name}
