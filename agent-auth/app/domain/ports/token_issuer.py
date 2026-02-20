from abc import ABC, abstractmethod

from app.domain.value_objects.principal import Principal


class TokenIssuer(ABC):
    @abstractmethod
    def issue_access(self, principal: Principal) -> str:
        raise NotImplementedError

    @abstractmethod
    def issue_refresh(self, principal: Principal) -> str:
        raise NotImplementedError
