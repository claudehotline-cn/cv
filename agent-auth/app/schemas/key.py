from datetime import datetime

from pydantic import BaseModel


class CreateApiKeyRequest(BaseModel):
    name: str
    scopes: dict | None = None
    expires_at: datetime | None = None


class CreateApiKeyResponse(BaseModel):
    id: str
    name: str
    key: str
    key_prefix: str


class ApiKeyItem(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
