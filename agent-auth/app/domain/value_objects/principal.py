from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    role: str
