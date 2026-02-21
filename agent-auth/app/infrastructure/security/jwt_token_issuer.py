from app.core.jwt import issue_access_token, issue_refresh_token
from app.domain.ports.token_issuer import TokenIssuer
from app.domain.value_objects.principal import Principal


class JwtTokenIssuer(TokenIssuer):
    def issue_access(self, principal: Principal) -> str:
        return issue_access_token(principal)

    def issue_refresh(self, principal: Principal) -> str:
        return issue_refresh_token(principal)
