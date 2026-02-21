from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ports.user_repo import UserRepository
from app.models.user import UserModel


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_email(self, email: str) -> UserModel | None:
        stmt = select(UserModel).where(UserModel.email == email)
        return await self.session.scalar(stmt)

    async def get_by_id(self, user_id: str) -> UserModel | None:
        stmt = select(UserModel).where(UserModel.id == user_id)
        return await self.session.scalar(stmt)

    async def create(self, *, email: str, username: str | None, password_hash: str, role: str) -> UserModel:
        user = UserModel(email=email, username=username, password_hash=password_hash, role=role)
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_last_login(self, user_id: str) -> None:
        user = await self.get_by_id(user_id)
        if user:
            user.last_login_at = datetime.utcnow()
