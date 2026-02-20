from app.core.errors import AuthError
from app.domain.ports.api_key_repo import ApiKeyRepository
from app.domain.ports.unit_of_work import UnitOfWork


class RevokeApiKeyService:
    def __init__(self, api_key_repo: ApiKeyRepository, uow: UnitOfWork):
        self.api_key_repo = api_key_repo
        self.uow = uow

    async def execute(self, *, key_id: str, user_id: str) -> None:
        ok = await self.api_key_repo.revoke(key_id, user_id)
        if not ok:
            raise AuthError("API key not found", status_code=404)
        await self.uow.commit()
