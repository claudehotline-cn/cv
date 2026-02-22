from __future__ import annotations

from typing import Any, Iterable

from ..ports.secrets import SecretInjector
from .secrets_service import SecretsService


class RuntimeSecretInjector(SecretInjector):
    def __init__(self, service: SecretsService):
        self.service = service

    async def resolve(self, *, tenant_id: str, user_id: str, secret_refs: Iterable[str]) -> dict[str, str]:
        return await self.service.resolve_secret_refs(
            tenant_id=tenant_id,
            user_id=user_id,
            secret_refs=secret_refs,
        )

    def inject(self, *, runtime_config: dict[str, Any], resolved: dict[str, str]) -> dict[str, Any]:
        out = dict(runtime_config or {})
        if resolved:
            out["secrets"] = resolved
        return out
