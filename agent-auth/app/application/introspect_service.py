from app.core.errors import AuthError
from app.core.config import get_settings
from app.domain.ports.api_key_verifier import ApiKeyVerifier
from app.domain.ports.token_verifier import TokenVerifier
from app.domain.value_objects.principal import Principal


class IntrospectService:
    def __init__(self, token_verifier: TokenVerifier, api_key_verifier: ApiKeyVerifier):
        self.token_verifier = token_verifier
        self.api_key_verifier = api_key_verifier

    async def execute(self, authorization: str | None, x_api_key: str | None = None) -> Principal:
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ", 1)[1].strip()
            return self.token_verifier.verify_access(token)

        # Support Authorization: ApiKey <key>
        if authorization and authorization.lower().startswith("apikey "):
            api_key = authorization.split(" ", 1)[1].strip()
            principal = await self.api_key_verifier.verify(api_key)
            if principal:
                return principal
            raise AuthError("Invalid API key", status_code=401)

        if x_api_key:
            principal = await self.api_key_verifier.verify(x_api_key)
            if principal:
                return principal
            raise AuthError("Invalid API key", status_code=401)

        raise AuthError("Missing authentication credentials", status_code=401)

    @staticmethod
    def tenant_context_for(principal: Principal) -> dict:
        settings = get_settings()
        # Phase 1: one default tenant; future phase maps memberships.
        return {
            "tenant_id": settings.auth_default_tenant_id,
            "tenant_role": "owner" if principal.role == "admin" else "member",
        }
