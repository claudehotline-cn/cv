from typing import Protocol, runtime_checkable

from app.platform_core.models import SemanticCacheKey, SemanticCacheValue


@runtime_checkable
class SemanticCachePort(Protocol):
    async def lookup(self, key: SemanticCacheKey) -> SemanticCacheValue | None:
        ...

    async def store(self, key: SemanticCacheKey, value: SemanticCacheValue) -> None:
        ...
