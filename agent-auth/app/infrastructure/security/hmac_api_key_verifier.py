from app.core.security import sha256_hex
from app.domain.ports.api_key_verifier import ApiKeyVerifier
from app.domain.ports.api_key_repo import ApiKeyRepository
from app.domain.ports.user_repo import UserRepository
from app.domain.value_objects.principal import Principal


class HmacApiKeyVerifier(ApiKeyVerifier):
    def __init__(self, api_key_repo: ApiKeyRepository, user_repo: UserRepository):
        self.api_key_repo = api_key_repo
        self.user_repo = user_repo

    async def verify(self, api_key: str) -> Principal | None:
        if not api_key:
            return None
        parts = api_key.split(".", 1)
        if len(parts) != 2:
            return None

        key_prefix = parts[0]
        key_hash = sha256_hex(api_key)
        key_row = await self.api_key_repo.get_active_by_prefix_and_hash(key_prefix, key_hash)
        if not key_row:
            return None

        user = await self.user_repo.get_by_id(key_row.user_id)
        if not user or user.status != "active":
            return None

        return Principal(user_id=user.id, email=user.email, role=user.role)
