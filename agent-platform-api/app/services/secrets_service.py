from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Iterable
from sqlalchemy.ext.asyncio import AsyncSession
from agent_core.settings import get_settings

from ..core.secrets_crypto import AesGcmCryptoProvider
from ..ports.secrets import SecretRepository
from .secrets_repository_mysql import MySQLSecretRepository
from .secrets_repository_pg import PostgresSecretRepository


@dataclass
class SecretRecord:
    id: str
    tenant_id: str
    owner_user_id: Optional[str]
    scope: str
    name: str
    provider: Optional[str]
    status: str
    current_version: int


class SecretsService:
    def __init__(self, db: AsyncSession, repository: SecretRepository | None = None):
        self.db = db
        self.crypto = AesGcmCryptoProvider()
        if repository is not None:
            self.repository = repository
        else:
            backend = (get_settings().secrets_store_backend or "postgres").strip().lower()
            if backend == "mysql":
                self.repository = MySQLSecretRepository()
            else:
                self.repository = PostgresSecretRepository(db)

    @staticmethod
    def _aad(tenant_id: str, secret_id: str, version: int, name: str, scope: str) -> bytes:
        return f"{tenant_id}|{secret_id}|{version}|{name}|{scope}".encode("utf-8")

    async def create_secret(
        self,
        *,
        tenant_id: str,
        owner_user_id: Optional[str],
        scope: str,
        name: str,
        provider: Optional[str],
        plaintext_value: str,
    ) -> SecretRecord:
        secret = await self.repository.create_secret(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            scope=scope,
            name=name,
            provider=provider,
        )
        aad = self._aad(secret.tenant_id, secret.id, 1, name, scope)
        blob = self.crypto.encrypt(plaintext_value, aad)

        await self.repository.append_version(
            secret_id=secret.id,
            version=1,
            crypto_alg=blob.crypto_alg,
            key_ref=blob.key_ref,
            nonce=blob.nonce_b64,
            ciphertext=blob.ciphertext_b64,
            enc_meta={"aad": "tenant|secret|version|name|scope"},
            fingerprint=blob.fingerprint,
        )
        await self.db.commit()
        return SecretRecord(
            id=secret.id,
            tenant_id=secret.tenant_id,
            owner_user_id=secret.owner_user_id,
            scope=secret.scope,
            name=secret.name,
            provider=secret.provider,
            status=secret.status,
            current_version=secret.current_version,
        )

    async def list_secrets(self, *, tenant_id: str, owner_user_id: Optional[str], scope: Optional[str]) -> list[SecretRecord]:
        rows = await self.repository.list_metadata(tenant_id=tenant_id, owner_user_id=owner_user_id, scope=scope)
        return [
            SecretRecord(
                id=s.id,
                tenant_id=s.tenant_id,
                owner_user_id=s.owner_user_id,
                scope=s.scope,
                name=s.name,
                provider=s.provider,
                status=s.status,
                current_version=s.current_version,
            )
            for s in rows
        ]

    async def get_secret_metadata(self, *, tenant_id: str, secret_id: str, user_id: Optional[str], is_admin: bool) -> SecretRecord:
        s = await self.repository.get_secret_metadata(tenant_id=tenant_id, secret_id=secret_id)
        if not s:
            raise ValueError("Secret not found")
        if not is_admin and s.scope == "user" and s.owner_user_id != user_id:
            raise PermissionError("Forbidden")
        return SecretRecord(
            id=s.id,
            tenant_id=s.tenant_id,
            owner_user_id=s.owner_user_id,
            scope=s.scope,
            name=s.name,
            provider=s.provider,
            status=s.status,
            current_version=s.current_version,
        )

    async def rotate_secret(self, *, tenant_id: str, secret_id: str, user_id: Optional[str], is_admin: bool, plaintext_value: str) -> SecretRecord:
        s = await self.repository.get_secret_metadata(tenant_id=tenant_id, secret_id=secret_id)
        if not s:
            raise ValueError("Secret not found")
        if not is_admin and s.scope == "user" and s.owner_user_id != user_id:
            raise PermissionError("Forbidden")

        next_version = int(s.current_version) + 1
        aad = self._aad(s.tenant_id, s.id, next_version, s.name, s.scope)
        blob = self.crypto.encrypt(plaintext_value, aad)
        await self.repository.append_version(
            secret_id=s.id,
            version=next_version,
            crypto_alg=blob.crypto_alg,
            key_ref=blob.key_ref,
            nonce=blob.nonce_b64,
            ciphertext=blob.ciphertext_b64,
            enc_meta={"aad": "tenant|secret|version|name|scope"},
            fingerprint=blob.fingerprint,
        )
        await self.repository.set_current_version(secret_id=s.id, version=next_version)
        await self.db.commit()
        return await self.get_secret_metadata(
            tenant_id=s.tenant_id,
            secret_id=s.id,
            user_id=user_id,
            is_admin=is_admin,
        )

    async def set_secret_status(
        self,
        *,
        tenant_id: str,
        secret_id: str,
        user_id: Optional[str],
        is_admin: bool,
        status: str,
    ) -> SecretRecord:
        s = await self.repository.get_secret_metadata(tenant_id=tenant_id, secret_id=secret_id)
        if not s:
            raise ValueError("Secret not found")
        if not is_admin and s.scope == "user" and s.owner_user_id != user_id:
            raise PermissionError("Forbidden")
        await self.repository.set_status(secret_id=s.id, status=status)
        await self.db.commit()
        return await self.get_secret_metadata(
            tenant_id=s.tenant_id,
            secret_id=s.id,
            user_id=user_id,
            is_admin=is_admin,
        )

    async def resolve_secret_value(
        self,
        *,
        tenant_id: str,
        user_id: str,
        name: str,
        scope: str = "user",
    ) -> Optional[str]:
        # scope arg kept for compatibility; repository handles user->tenant fallback
        _ = scope
        secret = await self.repository.find_by_ref(tenant_id=tenant_id, user_id=user_id, name=name)
        if not secret:
            return None

        version = await self.repository.get_version(secret_id=secret.id, version=secret.current_version)
        if not version:
            return None
        aad = self._aad(secret.tenant_id, secret.id, int(secret.current_version), secret.name, secret.scope)
        return self.crypto.decrypt(version.key_ref, version.nonce, version.ciphertext, aad)

    async def resolve_secret_refs(self, *, tenant_id: str, user_id: str, secret_refs: Iterable[str]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for raw in secret_refs:
            name = (raw or "").strip()
            if not name:
                continue
            value = await self.resolve_secret_value(
                tenant_id=tenant_id,
                user_id=user_id,
                name=name,
                scope="user",
            )
            if value is None:
                value = await self.resolve_secret_value(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    name=name,
                    scope="tenant",
                )
            if value is not None:
                resolved[name] = value
        return resolved
