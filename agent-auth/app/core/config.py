from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    app_name: str = "agent-auth"
    app_version: str = "0.1.0"

    auth_db_url: str = Field(
        default="mysql+aiomysql://root:123456@mysql:3306/agent_auth?charset=utf8mb4",
        alias="AGENT_AUTH_DB_URL",
    )
    auth_jwt_secret: str = Field(default="change-me-in-prod", alias="AGENT_AUTH_JWT_SECRET")
    auth_jwt_alg: str = Field(default="HS256", alias="AGENT_AUTH_JWT_ALG")
    auth_issuer: str = Field(default="agent-auth", alias="AGENT_AUTH_ISSUER")
    auth_audience: str = Field(default="agent-platform", alias="AGENT_AUTH_AUDIENCE")
    auth_access_ttl_min: int = Field(default=15, alias="AGENT_AUTH_ACCESS_TTL_MIN")
    auth_refresh_ttl_days: int = Field(default=14, alias="AGENT_AUTH_REFRESH_TTL_DAYS")
    auth_allow_register: bool = Field(default=False, alias="AGENT_AUTH_ALLOW_REGISTER")
    auth_rate_limit_login: str = Field(default="5/min", alias="AGENT_AUTH_RATE_LIMIT_LOGIN")
    auth_redis_url: str = Field(default="redis://langgraph-redis:6379/0", alias="AGENT_AUTH_REDIS_URL")
    auth_audit_stream_key: str = Field(default="audit.events", alias="AGENT_AUTH_AUDIT_STREAM_KEY")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
