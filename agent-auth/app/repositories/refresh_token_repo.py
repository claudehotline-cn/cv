from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ports.refresh_token_repo import RefreshTokenRepository
from app.models.refresh_token import RefreshTokenModel


class SqlAlchemyRefreshTokenRepository(RefreshTokenRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        user_id: str,
        token_hash: str,
        jti: str,
        expires_at: datetime,
        device_info: dict | None = None,
        ip_addr: str | None = None,
    ) -> RefreshTokenModel:
        row = RefreshTokenModel(
            user_id=user_id,
            token_hash=token_hash,
            jti=jti,
            expires_at=expires_at,
            device_info=device_info,
            ip_addr=ip_addr,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_active_by_jti(self, jti: str) -> RefreshTokenModel | None:
        stmt = select(RefreshTokenModel).where(
            and_(RefreshTokenModel.jti == jti, RefreshTokenModel.revoked_at.is_(None))
        )
        return await self.session.scalar(stmt)

    async def revoke_by_jti(self, jti: str) -> None:
        row = await self.get_active_by_jti(jti)
        if row:
            row.revoked_at = datetime.utcnow()

    async def revoke_all_for_user(self, user_id: str) -> None:
        stmt = select(RefreshTokenModel).where(
            and_(RefreshTokenModel.user_id == user_id, RefreshTokenModel.revoked_at.is_(None))
        )
        rows = (await self.session.scalars(stmt)).all()
        now = datetime.utcnow()
        for row in rows:
            row.revoked_at = now
