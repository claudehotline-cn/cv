from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_container, get_current_principal
from app.core.config import get_settings
from app.core.errors import AuthError
from app.domain.value_objects.principal import Principal
from app.infrastructure.wiring.container import Container
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
async def register(payload: RegisterRequest, container: Container = Depends(get_container)):
    settings = get_settings()
    if not settings.auth_allow_register:
        raise HTTPException(status_code=403, detail="Registration disabled")

    svc = container.register_service()
    try:
        user = await svc.execute(payload)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return UserResponse(id=user.id, email=user.email, username=user.username, role=user.role, status=user.status)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, container: Container = Depends(get_container)):
    svc = container.login_service()
    try:
        _, access, refresh = await svc.execute(payload)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    ttl_seconds = get_settings().auth_access_ttl_min * 60
    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=ttl_seconds)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, container: Container = Depends(get_container)):
    svc = container.refresh_service()
    try:
        access, refresh_token = await svc.execute(payload.refresh_token)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    ttl_seconds = get_settings().auth_access_ttl_min * 60
    return TokenResponse(access_token=access, refresh_token=refresh_token, expires_in=ttl_seconds)


@router.post("/logout")
async def logout(payload: LogoutRequest, container: Container = Depends(get_container)):
    svc = container.logout_service()
    try:
        await svc.logout(payload.refresh_token)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(
    principal: Principal = Depends(get_current_principal),
    container: Container = Depends(get_container),
):
    svc = container.logout_service()
    await svc.logout_all(principal.user_id)
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
async def me(principal: Principal = Depends(get_current_principal), container: Container = Depends(get_container)):
    user = await container.user_repo.get_by_id(principal.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(id=user.id, email=user.email, username=user.username, role=user.role, status=user.status)

