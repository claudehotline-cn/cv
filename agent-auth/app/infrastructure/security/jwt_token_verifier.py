from app.core.jwt import decode_and_validate, principal_from_payload
from app.domain.ports.token_verifier import TokenVerifier
from app.domain.value_objects.principal import Principal


class JwtTokenVerifier(TokenVerifier):
    def verify_access(self, token: str) -> Principal:
        payload = decode_and_validate(token, expected_type="access")
        return principal_from_payload(payload)

    def verify_refresh(self, token: str) -> Principal:
        payload = decode_and_validate(token, expected_type="refresh")
        return principal_from_payload(payload)
