from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import PlatformUserModel


class UserShadowService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_user(self, user_id: str, email: str | None, role: str | None) -> None:
        if not user_id:
            return
        row = await self.db.scalar(select(PlatformUserModel).where(PlatformUserModel.user_id == user_id))
        if row:
            changed = False
            if email and row.email != email:
                row.email = email
                changed = True
            if role and row.role != role:
                row.role = role
                changed = True
            if changed:
                await self.db.commit()
            return

        self.db.add(PlatformUserModel(user_id=user_id, email=email, role=role))
        await self.db.commit()

    async def update_role(self, user_id: str, role: str) -> None:
        if not user_id:
            return
        row = await self.db.scalar(select(PlatformUserModel).where(PlatformUserModel.user_id == user_id))
        if not row:
            self.db.add(PlatformUserModel(user_id=user_id, role=role))
            await self.db.commit()
            return
        if row.role != role:
            row.role = role
            await self.db.commit()
