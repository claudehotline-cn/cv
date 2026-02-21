from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ports.api_key_repo import ApiKeyRepository
from app.models.api_key import ApiKeyModel


class SqlAlchemyApiKeyRepository(ApiKeyRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        user_id: str,
        name: str,
        key_prefix: str,
        key_hash: str,
        scopes: dict | None,
        expires_at: datetime | None,
    ) -> ApiKeyModel:
        row = ApiKeyModel(
            user_id=user_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=scopes,
            expires_at=expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_active_for_user(self, user_id: str) -> list[ApiKeyModel]:
        stmt = select(ApiKeyModel).where(and_(ApiKeyModel.user_id == user_id, ApiKeyModel.revoked_at.is_(None)))
        return (await self.session.scalars(stmt)).all()

    async def revoke(self, key_id: str, user_id: str) -> bool:
        stmt = select(ApiKeyModel).where(
            and_(ApiKeyModel.id == key_id, ApiKeyModel.user_id == user_id, ApiKeyModel.revoked_at.is_(None))
        )
        row = await self.session.scalar(stmt)
        if not row:
            return False
        row.revoked_at = datetime.utcnow()
        return True

    async def get_active_by_prefix_and_hash(self, key_prefix: str, key_hash: str) -> ApiKeyModel | None:
        stmt = select(ApiKeyModel).where(
            and_(
                ApiKeyModel.key_prefix == key_prefix,
                ApiKeyModel.key_hash == key_hash,
                ApiKeyModel.revoked_at.is_(None),
            )
        )
        return await self.session.scalar(stmt)
