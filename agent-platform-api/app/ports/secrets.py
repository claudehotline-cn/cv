from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Protocol


@dataclass(frozen=True)
class SecretMetadata:
    id: str
    tenant_id: str
    owner_user_id: Optional[str]
    scope: str
    name: str
    provider: Optional[str]
    status: str
    current_version: int


@dataclass(frozen=True)
class SecretVersionData:
    id: str
    secret_id: str
    version: int
    crypto_alg: str
    key_ref: str
    nonce: str
    ciphertext: str
    enc_meta: Optional[dict[str, Any]]
    fingerprint: Optional[str]


class SecretRepository(Protocol):
    async def create_secret(
        self,
        *,
        tenant_id: str,
        owner_user_id: Optional[str],
        scope: str,
        name: str,
        provider: Optional[str],
    ) -> SecretMetadata: ...

    async def append_version(
        self,
        *,
        secret_id: str,
        version: int,
        crypto_alg: str,
        key_ref: str,
        nonce: str,
        ciphertext: str,
        enc_meta: Optional[dict[str, Any]],
        fingerprint: Optional[str],
    ) -> SecretVersionData: ...

    async def get_secret_metadata(
        self,
        *,
        tenant_id: str,
        secret_id: str,
    ) -> Optional[SecretMetadata]: ...

    async def list_metadata(
        self,
        *,
        tenant_id: str,
        owner_user_id: Optional[str],
        scope: Optional[str],
    ) -> list[SecretMetadata]: ...

    async def find_by_ref(
        self,
        *,
        tenant_id: str,
        user_id: str,
        name: str,
    ) -> Optional[SecretMetadata]: ...

    async def get_version(
        self,
        *,
        secret_id: str,
        version: int,
    ) -> Optional[SecretVersionData]: ...

    async def set_current_version(self, *, secret_id: str, version: int) -> None: ...

    async def set_status(self, *, secret_id: str, status: str) -> None: ...


class CryptoProvider(Protocol):
    def encrypt(self, plaintext: str, aad: bytes): ...

    def decrypt(self, key_ref: str, nonce_b64: str, ciphertext_b64: str, aad: bytes) -> str: ...


class SecretInjector(Protocol):
    async def resolve(self, *, tenant_id: str, user_id: str, secret_refs: Iterable[str]) -> dict[str, str]: ...

    def inject(self, *, runtime_config: dict[str, Any], resolved: dict[str, str]) -> dict[str, Any]: ...
