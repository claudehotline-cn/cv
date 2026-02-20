from functools import lru_cache
from typing import Dict, Optional

from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration for Agent Core."""
    
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    # LLM / provider settings
    llm_provider: str = Field(
        default="openai",
        description="LLM Provider: openai | ollama | vllm",
        alias="AGENT_LLM_PROVIDER",
    )
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
    llm_max_tokens: int = Field(
        default=4096,
        description="Max completion tokens for chat models",
        alias="AGENT_LLM_MAX_TOKENS",
    )
    ollama_base_url: str = Field(
        default="http://host.docker.internal:11434",
        description="Ollama Base URL",
        alias="AGENT_OLLAMA_BASE_URL",
    )
    vllm_base_url: str = Field(
        default="http://vllm:8000/v1",
        description="vLLM OpenAI-compatible API URL",
        alias="AGENT_VLLM_BASE_URL",
    )

    installed_agents: list[str] = Field(
        default=["data_agent"],
        description="List of installed agent plugins",
        alias="INSTALLED_AGENTS",
    )

    workspace_root: str = Field(
        default="/data/workspace",
        description="Root workspace directory for all agents",
        alias="WORKSPACE_ROOT",
    )

    redis_url: str = Field(
        default="redis://redis:6379",
        description="Redis Connection URL",
        alias="REDIS_URL",
    )

    # Task Queue Settings
    task_result_retention_hours: int = Field(
        default=24,
        description="Hours to retain task results before cleanup",
        alias="TASK_RESULT_RETENTION_HOURS",
    )

    # HTTP / Scraping Settings
    http_user_agent: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        alias="HTTP_USER_AGENT",
    )
    http_max_attempts: int = Field(
        default=3,
        alias="HTTP_MAX_ATTEMPTS",
    )
    http_timeout_sec: float = Field(
        default=30.0,
        alias="HTTP_TIMEOUT_SEC",
    )
    http_retry_backoff_sec: float = Field(
        default=1.0,
        alias="HTTP_RETRY_BACKOFF_SEC",
    )
    enable_playwright_fetch: bool = Field(
        default=False,
        description="Enable Playwright for JS rendering",
        alias="ENABLE_PLAYWRIGHT",
    )
    playwright_timeout_sec: int = Field(
        default=30,
        alias="PLAYWRIGHT_TIMEOUT_SEC",
    )
    use_trafilatura: bool = Field(
        default=True,
        description="Use trafilatura for content extraction",
        alias="USE_TRAFILATURA",
    )

    # MinIO / S3 Settings
    minio_endpoint: str = Field(
        default="minio:9000",
        description="MinIO Endpoint (host:port)",
        alias="AWS_ENDPOINT_URL_S3",
    )
    minio_access_key: str = Field(
        default="minioadmin",
        alias="AWS_ACCESS_KEY_ID",
    )
    minio_secret_key: str = Field(
        default="minioadmin123",
        alias="AWS_SECRET_ACCESS_KEY",
    )
    minio_secure: bool = Field(
        default=False,
        description="Use HTTPS for MinIO",
        alias="AWS_USE_HTTPS", # or inferred
    )
    minio_bucket: str = Field(
        default="article", # Default bucket for articles
        alias="ARTICLE_S3_BUCKET",
    )



    # Database Settings (Common)
    postgres_host: str = Field(
        default="pgvector",
        description="PostgreSQL Host (for Platform Infra)",
        alias="POSTGRES_HOST",
    )
    postgres_port: int = Field(
        default=5432,
        description="PostgreSQL Port",
        alias="POSTGRES_PORT",
    )
    postgres_user: str = Field(
        default="cv_kb",
        description="PostgreSQL User",
        alias="POSTGRES_USER",
    )
    postgres_password: str = Field(
        default="cv_kb_pass",
        description="PostgreSQL Password",
        alias="POSTGRES_PASSWORD",
    )
    postgres_db: str = Field(
        default="cv_kb",
        description="PostgreSQL Database Name",
        alias="POSTGRES_DB",
    )

    # External Data Source (Optional)
    db_host: str = Field(
        default="mysql",
        description="MySQL Host (Target Data Source)",
        alias="AGENT_DB_HOST",
    )
    db_port: int = Field(
        default=3306,
        description="MySQL Port",
        alias="AGENT_DB_PORT",
    )
    db_user: str = Field(
        default="root",
        description="MySQL User",
        alias="AGENT_DB_USER",
    )
    db_password: str = Field(
        default="123456",
        description="MySQL Password",
        alias="AGENT_DB_PASSWORD",
    )
    db_default_name: str = Field(
        default="cv_cp",
        description="Default MySQL Database Name",
        alias="AGENT_DB_DEFAULT_NAME",
    )
    db_extra_databases: Dict[str, str] = Field(
        default_factory=dict,
        description="Extra database aliases mapping (e.g., {'reporting': 'cv_reporting'})",
        alias="AGENT_DB_EXTRA_DATABASES",
    )
    
    # LLM & HTTP Timeouts
    request_timeout_sec: float = Field(
        default=30.0,
        alias="AGENT_REQUEST_TIMEOUT",
    )

    @property
    def postgres_uri(self) -> str:
        """PostgreSQL Connection URI"""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
