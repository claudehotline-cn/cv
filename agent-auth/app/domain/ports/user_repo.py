from abc import ABC, abstractmethod

from app.models.user import UserModel


class UserRepository(ABC):
    @abstractmethod
    async def get_by_email(self, email: str) -> UserModel | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, user_id: str) -> UserModel | None:
        raise NotImplementedError

    @abstractmethod
    async def create(self, *, email: str, username: str | None, password_hash: str, role: str) -> UserModel:
        raise NotImplementedError

    @abstractmethod
    async def update_last_login(self, user_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update_password_hash(self, user_id: str, password_hash: str) -> bool:
        raise NotImplementedError
