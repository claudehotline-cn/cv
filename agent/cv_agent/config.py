from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration for the agent service."""

    # LLM / provider settings
    openai_api_key: Optional[str] = Field(
        default=None,
        description="API key for OpenAI-compatible chat models",
        alias="OPENAI_API_KEY",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="Model name for the chat LLM",
        alias="AGENT_OPENAI_MODEL",
    )

    # Downstream services
    cp_base_url: str = Field(
        default="http://localhost:8080",
        description="Base URL for ControlPlane HTTP API (e.g. http://cp:8080)",
        alias="AGENT_CP_BASE_URL",
    )
    request_timeout_sec: float = Field(
        default=10.0,
        description="Default timeout (seconds) for downstream HTTP requests",
        alias="AGENT_REQUEST_TIMEOUT",
    )

    # Checkpoint backend
    checkpoint_backend: str = Field(
        default="memory",
        description="Checkpoint 后端类型：memory 或 sqlite（预留 mysql）",
        alias="AGENT_CHECKPOINT_BACKEND",
    )
    checkpoint_sqlite_conn: Optional[str] = Field(
        default=None,
        description="SQLite checkpoint 连接串，例如 'checkpoints.sqlite' 或 ':memory:'",
        alias="AGENT_CHECKPOINT_SQLITE_CONN",
    )
    checkpoint_mysql_dsn: Optional[str] = Field(
        default=None,
        description="预留的 MySQL checkpoint DSN（当前未实现）",
        alias="AGENT_CHECKPOINT_MYSQL_DSN",
    )

    # Service behaviour
    log_level: str = Field(
        default="INFO",
        description="Log level for the agent service",
        alias="AGENT_LOG_LEVEL",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide Settings instance."""

    return Settings()  # type: ignore[call-arg]
