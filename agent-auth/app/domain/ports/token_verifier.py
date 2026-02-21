from abc import ABC, abstractmethod

from app.domain.value_objects.principal import Principal


class TokenVerifier(ABC):
    @abstractmethod
    def verify_access(self, token: str) -> Principal:
        raise NotImplementedError

    @abstractmethod
    def verify_refresh(self, token: str) -> Principal:
        raise NotImplementedError
