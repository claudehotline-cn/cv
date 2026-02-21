from abc import ABC, abstractmethod
from datetime import datetime

from app.models.api_key import ApiKeyModel


class ApiKeyRepository(ABC):
    @abstractmethod
    async def create(
        self,
        *,
        user_id: str,
        name: str,
        key_prefix: str,
        key_hash: str,
        scopes: dict | None,
        expires_at: datetime | None,
    ) -> ApiKeyModel:
        raise NotImplementedError

    @abstractmethod
    async def list_active_for_user(self, user_id: str) -> list[ApiKeyModel]:
        raise NotImplementedError

    @abstractmethod
    async def revoke(self, key_id: str, user_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def get_active_by_prefix_and_hash(self, key_prefix: str, key_hash: str) -> ApiKeyModel | None:
        raise NotImplementedError
