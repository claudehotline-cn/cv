from fastapi import APIRouter, Depends

from app.api.deps import get_container, get_current_principal
from app.domain.value_objects.principal import Principal
from app.infrastructure.wiring.container import Container
from app.schemas.key import ApiKeyItem, CreateApiKeyRequest, CreateApiKeyResponse


router = APIRouter(prefix="/auth/api-keys", tags=["auth"])


@router.post("", response_model=CreateApiKeyResponse)
async def create_api_key(
    payload: CreateApiKeyRequest,
    principal: Principal = Depends(get_current_principal),
    container: Container = Depends(get_container),
):
    row, raw_key = await container.create_api_key_service().execute(
        user_id=principal.user_id,
        name=payload.name,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
    )
    return CreateApiKeyResponse(id=row.id, name=row.name, key=raw_key, key_prefix=row.key_prefix)


@router.get("", response_model=list[ApiKeyItem])
async def list_api_keys(
    principal: Principal = Depends(get_current_principal),
    container: Container = Depends(get_container),
):
    rows = await container.api_key_repo.list_active_for_user(principal.user_id)
    return [
        ApiKeyItem(
            id=row.id,
            name=row.name,
            key_prefix=row.key_prefix,
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
        )
        for row in rows
    ]


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: str,
    principal: Principal = Depends(get_current_principal),
    container: Container = Depends(get_container),
):
    await container.revoke_api_key_service().execute(key_id=key_id, user_id=principal.user_id)
    return {"ok": True}
