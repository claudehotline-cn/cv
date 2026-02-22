from __future__ import annotations

from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import SecretModel, SecretVersionModel
from ..ports.secrets import SecretMetadata, SecretRepository, SecretVersionData


def _to_secret_metadata(s: SecretModel) -> SecretMetadata:
    return SecretMetadata(
        id=str(s.id),
        tenant_id=str(s.tenant_id),
        owner_user_id=s.owner_user_id,
        scope=s.scope,
        name=s.name,
        provider=s.provider,
        status=s.status,
        current_version=s.current_version,
    )


def _to_secret_version(v: SecretVersionModel) -> SecretVersionData:
    return SecretVersionData(
        id=str(v.id),
        secret_id=str(v.secret_id),
        version=v.version,
        crypto_alg=v.crypto_alg,
        key_ref=v.key_ref,
        nonce=v.nonce,
        ciphertext=v.ciphertext,
        enc_meta=v.enc_meta,
        fingerprint=v.fingerprint,
    )


class PostgresSecretRepository(SecretRepository):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_secret(
        self,
        *,
        tenant_id: str,
        owner_user_id: Optional[str],
        scope: str,
        name: str,
        provider: Optional[str],
    ) -> SecretMetadata:
        tenant_uuid = UUID(str(tenant_id))
        existing = await self.db.scalar(
            select(SecretModel).where(
                SecretModel.tenant_id == tenant_uuid,
                SecretModel.scope == scope,
                SecretModel.owner_user_id == owner_user_id,
                SecretModel.name == name,
                SecretModel.status != "deleted",
            )
        )
        if existing:
            raise ValueError("Secret already exists")

        s = SecretModel(
            id=uuid4(),
            tenant_id=tenant_uuid,
            owner_user_id=owner_user_id,
            scope=scope,
            name=name,
            provider=provider,
            status="active",
            current_version=1,
        )
        self.db.add(s)
        await self.db.flush()
        return _to_secret_metadata(s)

    async def append_version(
        self,
        *,
        secret_id: str,
        version: int,
        crypto_alg: str,
        key_ref: str,
        nonce: str,
        ciphertext: str,
        enc_meta: Optional[dict],
        fingerprint: Optional[str],
    ) -> SecretVersionData:
        v = SecretVersionModel(
            id=uuid4(),
            secret_id=UUID(str(secret_id)),
            version=version,
            crypto_alg=crypto_alg,
            key_ref=key_ref,
            nonce=nonce,
            ciphertext=ciphertext,
            enc_meta=enc_meta,
            fingerprint=fingerprint,
        )
        self.db.add(v)
        await self.db.flush()
        return _to_secret_version(v)

    async def get_secret_metadata(self, *, tenant_id: str, secret_id: str) -> Optional[SecretMetadata]:
        s = await self.db.scalar(
            select(SecretModel).where(
                SecretModel.id == UUID(str(secret_id)),
                SecretModel.tenant_id == UUID(str(tenant_id)),
                SecretModel.status != "deleted",
            )
        )
        return _to_secret_metadata(s) if s else None

    async def list_metadata(self, *, tenant_id: str, owner_user_id: Optional[str], scope: Optional[str]) -> list[SecretMetadata]:
        stmt = select(SecretModel).where(
            SecretModel.tenant_id == UUID(str(tenant_id)),
            SecretModel.status != "deleted",
        )
        if owner_user_id:
            stmt = stmt.where((SecretModel.owner_user_id == owner_user_id) | (SecretModel.scope == "tenant"))
        if scope:
            stmt = stmt.where(SecretModel.scope == scope)
        rows = (await self.db.execute(stmt.order_by(SecretModel.created_at.desc()))).scalars().all()
        return [_to_secret_metadata(s) for s in rows]

    async def find_by_ref(self, *, tenant_id: str, user_id: str, name: str) -> Optional[SecretMetadata]:
        tenant_uuid = UUID(str(tenant_id))
        user_secret = await self.db.scalar(
            select(SecretModel).where(
                SecretModel.tenant_id == tenant_uuid,
                SecretModel.name == name,
                SecretModel.scope == "user",
                SecretModel.owner_user_id == user_id,
                SecretModel.status == "active",
            )
        )
        if user_secret:
            return _to_secret_metadata(user_secret)
        tenant_secret = await self.db.scalar(
            select(SecretModel).where(
                SecretModel.tenant_id == tenant_uuid,
                SecretModel.name == name,
                SecretModel.scope == "tenant",
                SecretModel.status == "active",
            )
        )
        return _to_secret_metadata(tenant_secret) if tenant_secret else None

    async def get_version(self, *, secret_id: str, version: int) -> Optional[SecretVersionData]:
        v = await self.db.scalar(
            select(SecretVersionModel).where(
                SecretVersionModel.secret_id == UUID(str(secret_id)),
                SecretVersionModel.version == version,
            )
        )
        return _to_secret_version(v) if v else None

    async def set_current_version(self, *, secret_id: str, version: int) -> None:
        s = await self.db.scalar(select(SecretModel).where(SecretModel.id == UUID(str(secret_id))))
        if s:
            s.current_version = version

    async def set_status(self, *, secret_id: str, status: str) -> None:
        s = await self.db.scalar(select(SecretModel).where(SecretModel.id == UUID(str(secret_id))))
        if s:
            s.status = status
