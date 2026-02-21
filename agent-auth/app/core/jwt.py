from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.errors import AuthError
from app.domain.value_objects.principal import Principal


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _issue_token(principal: Principal, token_type: str, ttl_seconds: int) -> str:
    settings = get_settings()
    now = _now_utc()
    payload = {
        "sub": principal.user_id,
        "email": principal.email,
        "role": principal.role,
        "type": token_type,
        "jti": str(uuid4()),
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm=settings.auth_jwt_alg)


def issue_access_token(principal: Principal) -> str:
    settings = get_settings()
    return _issue_token(principal, "access", settings.auth_access_ttl_min * 60)


def issue_refresh_token(principal: Principal) -> str:
    settings = get_settings()
    return _issue_token(principal, "refresh", settings.auth_refresh_ttl_days * 24 * 3600)


def decode_and_validate(token: str, expected_type: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_alg],
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
        )
    except JWTError as exc:
        raise AuthError("Invalid token", status_code=401) from exc

    if payload.get("type") != expected_type:
        raise AuthError("Invalid token type", status_code=401)

    required = ["sub", "email", "role", "jti"]
    if any(not payload.get(k) for k in required):
        raise AuthError("Malformed token", status_code=401)

    return payload


def principal_from_payload(payload: dict) -> Principal:
    return Principal(user_id=payload["sub"], email=payload["email"], role=payload["role"])
