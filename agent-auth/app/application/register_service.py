from app.core.errors import AuthError
from app.domain.ports.password_hasher import PasswordHasher
from app.domain.ports.user_repo import UserRepository
from app.domain.ports.unit_of_work import UnitOfWork
from app.schemas.auth import RegisterRequest


class RegisterService:
    def __init__(self, user_repo: UserRepository, hasher: PasswordHasher, uow: UnitOfWork):
        self.user_repo = user_repo
        self.hasher = hasher
        self.uow = uow

    async def execute(self, payload: RegisterRequest):
        exists = await self.user_repo.get_by_email(payload.email)
        if exists:
            raise AuthError("Email already exists", status_code=409)

        password_hash = self.hasher.hash(payload.password)
        user = await self.user_repo.create(
            email=payload.email,
            username=payload.username,
            password_hash=password_hash,
            role="user",
        )
        await self.uow.commit()
        return user
