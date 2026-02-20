from sqlalchemy.ext.asyncio import AsyncSession

from app.application.create_api_key_service import CreateApiKeyService
from app.application.introspect_service import IntrospectService
from app.application.login_service import LoginService
from app.application.logout_service import LogoutService
from app.application.refresh_service import RefreshService
from app.application.register_service import RegisterService
from app.application.revoke_api_key_service import RevokeApiKeyService
from app.domain.ports.unit_of_work import UnitOfWork
from app.infrastructure.security.bcrypt_hasher import BcryptPasswordHasher
from app.infrastructure.security.jwt_token_issuer import JwtTokenIssuer
from app.infrastructure.security.jwt_token_verifier import JwtTokenVerifier
from app.repositories.api_key_repo import SqlAlchemyApiKeyRepository
from app.repositories.refresh_token_repo import SqlAlchemyRefreshTokenRepository
from app.repositories.user_repo import SqlAlchemyUserRepository


class SqlAlchemyUnitOfWork(UnitOfWork):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


class Container:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_repo = SqlAlchemyUserRepository(session)
        self.refresh_repo = SqlAlchemyRefreshTokenRepository(session)
        self.api_key_repo = SqlAlchemyApiKeyRepository(session)
        self.hasher = BcryptPasswordHasher()
        self.token_issuer = JwtTokenIssuer()
        self.token_verifier = JwtTokenVerifier()
        self.uow = SqlAlchemyUnitOfWork(session)

    def register_service(self) -> RegisterService:
        return RegisterService(self.user_repo, self.hasher, self.uow)

    def login_service(self) -> LoginService:
        return LoginService(self.user_repo, self.hasher, self.token_issuer, self.refresh_repo, self.uow)

    def refresh_service(self) -> RefreshService:
        return RefreshService(self.user_repo, self.refresh_repo, self.token_issuer, self.uow)

    def logout_service(self) -> LogoutService:
        return LogoutService(self.refresh_repo, self.uow)

    def create_api_key_service(self) -> CreateApiKeyService:
        return CreateApiKeyService(self.api_key_repo, self.uow)

    def revoke_api_key_service(self) -> RevokeApiKeyService:
        return RevokeApiKeyService(self.api_key_repo, self.uow)

    def introspect_service(self) -> IntrospectService:
        return IntrospectService(self.token_verifier)
