from datetime import datetime, timedelta

from app.core.config import get_settings
from app.core.errors import AuthError
from app.core.jwt import decode_and_validate
from app.core.security import sha256_hex
from app.domain.ports.refresh_token_repo import RefreshTokenRepository
from app.domain.ports.token_issuer import TokenIssuer
from app.domain.ports.unit_of_work import UnitOfWork
from app.domain.ports.user_repo import UserRepository
from app.domain.value_objects.principal import Principal


class RefreshService:
    def __init__(
        self,
        user_repo: UserRepository,
        refresh_repo: RefreshTokenRepository,
        token_issuer: TokenIssuer,
        uow: UnitOfWork,
    ):
        self.user_repo = user_repo
        self.refresh_repo = refresh_repo
        self.token_issuer = token_issuer
        self.uow = uow

    async def execute(self, refresh_token: str):
        payload = decode_and_validate(refresh_token, expected_type="refresh")
        row = await self.refresh_repo.get_active_by_jti(payload["jti"])
        if not row:
            raise AuthError("Refresh token revoked", status_code=401)
        if row.token_hash != sha256_hex(refresh_token):
            raise AuthError("Invalid refresh token", status_code=401)
        if row.expires_at < datetime.utcnow():
            raise AuthError("Refresh token expired", status_code=401)

        user = await self.user_repo.get_by_id(payload["sub"])
        if not user or user.status != "active":
            raise AuthError("User unavailable", status_code=401)

        await self.refresh_repo.revoke_by_jti(payload["jti"])
        principal = Principal(user_id=user.id, email=user.email, role=user.role)
        new_access = self.token_issuer.issue_access(principal)
        new_refresh = self.token_issuer.issue_refresh(principal)

        new_payload = decode_and_validate(new_refresh, expected_type="refresh")
        settings = get_settings()
        expires_at = datetime.utcnow() + timedelta(days=settings.auth_refresh_ttl_days)
        await self.refresh_repo.create(
            user_id=user.id,
            token_hash=sha256_hex(new_refresh),
            jti=new_payload["jti"],
            expires_at=expires_at,
        )
        await self.uow.commit()
        return new_access, new_refresh
