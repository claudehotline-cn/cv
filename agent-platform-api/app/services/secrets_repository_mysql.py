from __future__ import annotations

from typing import Optional

from ..ports.secrets import SecretMetadata, SecretRepository, SecretVersionData


class MySQLSecretRepository(SecretRepository):
    """
    Placeholder for MySQL-backed secrets repository.
    Keeps application layer decoupled from storage backend.
    """

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError("MySQLSecretRepository is not implemented in M1")

    async def create_secret(self, *, tenant_id: str, owner_user_id: Optional[str], scope: str, name: str, provider: Optional[str]) -> SecretMetadata:
        raise NotImplementedError

    async def append_version(self, *, secret_id: str, version: int, crypto_alg: str, key_ref: str, nonce: str, ciphertext: str, enc_meta: Optional[dict], fingerprint: Optional[str]) -> SecretVersionData:
        raise NotImplementedError

    async def get_secret_metadata(self, *, tenant_id: str, secret_id: str) -> Optional[SecretMetadata]:
        raise NotImplementedError

    async def list_metadata(self, *, tenant_id: str, owner_user_id: Optional[str], scope: Optional[str]) -> list[SecretMetadata]:
        raise NotImplementedError

    async def find_by_ref(self, *, tenant_id: str, user_id: str, name: str) -> Optional[SecretMetadata]:
        raise NotImplementedError

    async def get_version(self, *, secret_id: str, version: int) -> Optional[SecretVersionData]:
        raise NotImplementedError

    async def set_current_version(self, *, secret_id: str, version: int) -> None:
        raise NotImplementedError

    async def set_status(self, *, secret_id: str, status: str) -> None:
        raise NotImplementedError
