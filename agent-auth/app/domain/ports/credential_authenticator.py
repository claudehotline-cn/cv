from abc import ABC, abstractmethod

from app.models.user import UserModel


class CredentialAuthenticator(ABC):
    @abstractmethod
    async def authenticate(self, email: str, password: str) -> UserModel | None:
        raise NotImplementedError
