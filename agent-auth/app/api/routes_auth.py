from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_container, get_current_principal
from app.core.config import get_settings
from app.core.errors import AuthError
from app.core.rate_limit import clear_login_failures, consume_login_failure
from app.domain.value_objects.principal import Principal
from app.infrastructure.wiring.container import Container
from app.schemas.auth import (
    ChangePasswordRequest,
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
async def login(payload: LoginRequest, request: Request, container: Container = Depends(get_container)):
    ip = request.client.host if request.client else "unknown"
    limiter_key = f"login:{payload.email.lower()}:{ip}"
    svc = container.login_service()
    try:
        _, access, refresh = await svc.execute(payload)
    except AuthError as exc:
        if exc.status_code == 401:
            allowed, retry_after = await consume_login_failure(limiter_key)
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many login attempts, retry after {retry_after}s",
                ) from exc
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    await clear_login_failures(limiter_key)
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


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    principal: Principal = Depends(get_current_principal),
    container: Container = Depends(get_container),
):
    user = await container.user_repo.get_by_id(principal.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not container.hasher.verify(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid current password")

    new_hash = container.hasher.hash(payload.new_password)
    ok = await container.user_repo.update_password_hash(principal.user_id, new_hash)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    await container.uow.commit()
    return {"ok": True}
