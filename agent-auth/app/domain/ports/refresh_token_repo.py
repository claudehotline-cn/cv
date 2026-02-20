from abc import ABC, abstractmethod
from datetime import datetime

from app.models.refresh_token import RefreshTokenModel


class RefreshTokenRepository(ABC):
    @abstractmethod
    async def create(
        self,
        *,
        user_id: str,
        token_hash: str,
        jti: str,
        expires_at: datetime,
        device_info: dict | None = None,
        ip_addr: str | None = None,
    ) -> RefreshTokenModel:
        raise NotImplementedError

    @abstractmethod
    async def get_active_by_jti(self, jti: str) -> RefreshTokenModel | None:
        raise NotImplementedError

    @abstractmethod
    async def revoke_by_jti(self, jti: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def revoke_all_for_user(self, user_id: str) -> None:
        raise NotImplementedError
