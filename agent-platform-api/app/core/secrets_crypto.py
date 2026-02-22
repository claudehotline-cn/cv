import base64
import hashlib
import os
import logging
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agent_core.settings import get_settings


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EncryptedBlob:
    crypto_alg: str
    key_ref: str
    nonce_b64: str
    ciphertext_b64: str
    fingerprint: str


class KeyProvider:
    def active_key_ref(self) -> str:
        raise NotImplementedError

    def get_key(self, key_ref: str) -> bytes:
        raise NotImplementedError


class EnvKeyProvider(KeyProvider):
    def __init__(self):
        settings = get_settings()
        self._active = (settings.secrets_active_key_ref or "default").strip() or "default"
        self._keys: dict[str, bytes] = {}

        ring = (settings.secrets_encryption_keys or "").strip()
        if ring:
            for part in ring.split(","):
                item = part.strip()
                if not item or ":" not in item:
                    continue
                ref, raw = item.split(":", 1)
                ref = ref.strip()
                raw = raw.strip()
                if not ref or not raw:
                    continue
                self._keys[ref] = _decode_key(raw)

        # backward-compatible single key
        if not self._keys:
            fallback = (settings.secrets_encryption_key or "").strip()
            if fallback:
                self._keys[self._active] = _decode_key(fallback)

        # local/dev fallback to avoid hard failure when env key is missing.
        if not self._keys:
            seed = f"{settings.redis_url}|{settings.postgres_host}|{settings.postgres_password}|{settings.auth_default_tenant_id}"
            self._keys[self._active] = hashlib.sha256(seed.encode("utf-8")).digest()
            _LOGGER.warning("SECRETS_ENCRYPTION_KEYS not set, using derived fallback key for current environment")

    def active_key_ref(self) -> str:
        return self._active

    def get_key(self, key_ref: str) -> bytes:
        key = self._keys.get(key_ref)
        if not key:
            raise ValueError("Secret encryption key not found")
        return key


def _decode_key(raw: str) -> bytes:
    pad_len = (4 - len(raw) % 4) % 4
    key = base64.urlsafe_b64decode(raw + ("=" * pad_len))
    if len(key) != 32:
        raise ValueError("Secrets key must be 32 bytes")
    return key


class AesGcmCryptoProvider:
    def __init__(self, key_provider: KeyProvider | None = None):
        self.key_provider = key_provider or EnvKeyProvider()

    def encrypt(self, plaintext: str, aad: bytes) -> EncryptedBlob:
        key_ref = self.key_provider.active_key_ref()
        key = self.key_provider.get_key(key_ref)
        aes = AESGCM(key)
        nonce = os.urandom(12)
        cipher = aes.encrypt(nonce, plaintext.encode("utf-8"), aad)
        fp = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:16]
        return EncryptedBlob(
            crypto_alg="aes_gcm_v1",
            key_ref=key_ref,
            nonce_b64=base64.urlsafe_b64encode(nonce).decode("utf-8"),
            ciphertext_b64=base64.urlsafe_b64encode(cipher).decode("utf-8"),
            fingerprint=fp,
        )

    def decrypt(self, key_ref: str, nonce_b64: str, ciphertext_b64: str, aad: bytes) -> str:
        key = self.key_provider.get_key(key_ref)
        aes = AESGCM(key)
        nonce = base64.urlsafe_b64decode(nonce_b64)
        cipher = base64.urlsafe_b64decode(ciphertext_b64)
        plain = aes.decrypt(nonce, cipher, aad)
        return plain.decode("utf-8")
