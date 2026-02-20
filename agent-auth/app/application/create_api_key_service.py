from datetime import datetime

from app.core.security import generate_api_key, sha256_hex
from app.domain.ports.api_key_repo import ApiKeyRepository
from app.domain.ports.unit_of_work import UnitOfWork


class CreateApiKeyService:
    def __init__(self, api_key_repo: ApiKeyRepository, uow: UnitOfWork):
        self.api_key_repo = api_key_repo
        self.uow = uow

    async def execute(
        self,
        *,
        user_id: str,
        name: str,
        scopes: dict | None = None,
        expires_at: datetime | None = None,
    ):
        raw_key, key_prefix = generate_api_key()
        row = await self.api_key_repo.create(
            user_id=user_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=sha256_hex(raw_key),
            scopes=scopes,
            expires_at=expires_at,
        )
        await self.uow.commit()
        return row, raw_key
