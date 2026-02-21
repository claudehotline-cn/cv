from app.domain.ports.password_hasher import PasswordHasher
from app.core.password import hash_password, verify_password


class BcryptPasswordHasher(PasswordHasher):
    def hash(self, raw_password: str) -> str:
        return hash_password(raw_password)

    def verify(self, raw_password: str, hashed_password: str) -> bool:
        return verify_password(raw_password, hashed_password)
