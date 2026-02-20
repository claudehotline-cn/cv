from app.core.errors import AuthError
from app.domain.ports.token_verifier import TokenVerifier
from app.domain.value_objects.principal import Principal


class IntrospectService:
    def __init__(self, token_verifier: TokenVerifier):
        self.token_verifier = token_verifier

    def execute(self, authorization: str | None) -> Principal:
        if not authorization:
            raise AuthError("Missing Authorization header", status_code=401)
        if not authorization.startswith("Bearer "):
            raise AuthError("Invalid Authorization header", status_code=401)
        token = authorization.split(" ", 1)[1].strip()
        return self.token_verifier.verify_access(token)
