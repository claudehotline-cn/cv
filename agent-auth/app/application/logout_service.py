from app.core.errors import AuthError
from app.core.jwt import decode_and_validate
from app.domain.ports.refresh_token_repo import RefreshTokenRepository
from app.domain.ports.unit_of_work import UnitOfWork


class LogoutService:
    def __init__(self, refresh_repo: RefreshTokenRepository, uow: UnitOfWork):
        self.refresh_repo = refresh_repo
        self.uow = uow

    async def logout(self, refresh_token: str) -> None:
        payload = decode_and_validate(refresh_token, expected_type="refresh")
        await self.refresh_repo.revoke_by_jti(payload["jti"])
        await self.uow.commit()

    async def logout_all(self, user_id: str) -> None:
        if not user_id:
            raise AuthError("Invalid user", status_code=400)
        await self.refresh_repo.revoke_all_for_user(user_id)
        await self.uow.commit()
