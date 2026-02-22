from __future__ import annotations

from typing import Any


SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "secret_key",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "private_key",
}


def _is_sensitive_key(key: str) -> bool:
    k = (key or "").strip().lower()
    if k in SENSITIVE_KEYS:
        return True
    return any(part in k for part in ("secret", "token", "password", "api_key", "apikey"))


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return redact_payload(value)
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if _is_sensitive_key(k):
            out[k] = "***REDACTED***"
        elif isinstance(v, dict):
            out[k] = redact_payload(v)
        elif isinstance(v, list):
            out[k] = [redact_value(item) for item in v]
        else:
            out[k] = v
    return out
