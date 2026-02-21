from abc import ABC, abstractmethod

from app.domain.value_objects.principal import Principal


class ApiKeyVerifier(ABC):
    @abstractmethod
    async def verify(self, api_key: str) -> Principal | None:
        raise NotImplementedError
