import hashlib
import secrets


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_api_key(prefix: str = "ak_live") -> tuple[str, str]:
    left = secrets.token_hex(4)
    right = secrets.token_urlsafe(24)
    key = f"{prefix}_{left}.{right}"
    return key, f"{prefix}_{left}"
