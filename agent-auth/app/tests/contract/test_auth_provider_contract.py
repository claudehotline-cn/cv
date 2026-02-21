from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.core.config import get_settings
from app.core.errors import AuthError
from app.domain.value_objects.principal import Principal
from app.infrastructure.security.jwt_token_issuer import JwtTokenIssuer
from app.infrastructure.security.jwt_token_verifier import JwtTokenVerifier


def _run_provider_contract(token_issuer, token_verifier) -> None:
    principal = Principal(user_id="u-123", email="u@example.com", role="admin")

    access = token_issuer.issue_access(principal)
    refresh = token_issuer.issue_refresh(principal)

    verified_access = token_verifier.verify_access(access)
    verified_refresh = token_verifier.verify_refresh(refresh)

    assert verified_access.user_id == principal.user_id
    assert verified_access.email == principal.email
    assert verified_access.role == principal.role

    assert verified_refresh.user_id == principal.user_id
    assert verified_refresh.email == principal.email
    assert verified_refresh.role == principal.role


def _make_token(payload: dict) -> str:
    settings = get_settings()
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm=settings.auth_jwt_alg)


def _base_payload(token_type: str) -> dict:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return {
        "sub": "u-123",
        "email": "u@example.com",
        "role": "user",
        "type": token_type,
        "jti": "jti-123",
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }


@pytest.mark.contract
def test_jwt_provider_contract_success() -> None:
    _run_provider_contract(JwtTokenIssuer(), JwtTokenVerifier())


@pytest.mark.contract
def test_jwt_provider_contract_rejects_wrong_token_type() -> None:
    verifier = JwtTokenVerifier()
    payload = _base_payload("refresh")
    token = _make_token(payload)

    with pytest.raises(AuthError) as exc:
        verifier.verify_access(token)
    assert exc.value.status_code == 401
    assert "type" in exc.value.message.lower()


@pytest.mark.contract
def test_jwt_provider_contract_rejects_expired_token() -> None:
    verifier = JwtTokenVerifier()
    payload = _base_payload("access")
    payload["exp"] = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    token = _make_token(payload)

    with pytest.raises(AuthError) as exc:
        verifier.verify_access(token)
    assert exc.value.status_code == 401


@pytest.mark.contract
def test_jwt_provider_contract_rejects_malformed_claims() -> None:
    verifier = JwtTokenVerifier()
    payload = _base_payload("access")
    payload.pop("jti", None)
    token = _make_token(payload)

    with pytest.raises(AuthError) as exc:
        verifier.verify_access(token)
    assert exc.value.status_code == 401
    assert "malformed" in exc.value.message.lower()


@pytest.mark.contract
def test_jwt_provider_contract_rejects_invalid_signature() -> None:
    verifier = JwtTokenVerifier()
    payload = _base_payload("access")
    token = jwt.encode(payload, "wrong-secret", algorithm=get_settings().auth_jwt_alg)

    with pytest.raises(AuthError) as exc:
        verifier.verify_access(token)
    assert exc.value.status_code == 401
