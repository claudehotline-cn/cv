from datetime import datetime, timedelta

from app.core.config import get_settings
from app.core.errors import AuthError
from app.core.jwt import decode_and_validate
from app.core.security import sha256_hex
from app.domain.ports.password_hasher import PasswordHasher
from app.domain.ports.refresh_token_repo import RefreshTokenRepository
from app.domain.ports.token_issuer import TokenIssuer
from app.domain.ports.unit_of_work import UnitOfWork
from app.domain.ports.user_repo import UserRepository
from app.domain.value_objects.principal import Principal
from app.schemas.auth import LoginRequest


class LoginService:
    def __init__(
        self,
        user_repo: UserRepository,
        hasher: PasswordHasher,
        token_issuer: TokenIssuer,
        refresh_repo: RefreshTokenRepository,
        uow: UnitOfWork,
    ):
        self.user_repo = user_repo
        self.hasher = hasher
        self.token_issuer = token_issuer
        self.refresh_repo = refresh_repo
        self.uow = uow

    async def execute(self, payload: LoginRequest):
        user = await self.user_repo.get_by_email(payload.email)
        if not user or not self.hasher.verify(payload.password, user.password_hash):
            raise AuthError("Invalid credentials", status_code=401)
        if user.status != "active":
            raise AuthError("User disabled", status_code=403)

        principal = Principal(user_id=user.id, email=user.email, role=user.role)
        access_token = self.token_issuer.issue_access(principal)
        refresh_token = self.token_issuer.issue_refresh(principal)

        refresh_payload = decode_and_validate(refresh_token, expected_type="refresh")
        settings = get_settings()
        expires_at = datetime.utcnow() + timedelta(days=settings.auth_refresh_ttl_days)
        await self.refresh_repo.create(
            user_id=user.id,
            token_hash=sha256_hex(refresh_token),
            jti=refresh_payload["jti"],
            expires_at=expires_at,
        )
        await self.user_repo.update_last_login(user.id)
        await self.uow.commit()

        return user, access_token, refresh_token
