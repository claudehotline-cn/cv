from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration for the agent service."""

    # LLM / provider settings
    llm_provider: str = Field(
        default="openai",
        description="LLM 提供方：openai 或 ollama",
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
    ollama_base_url: str = Field(
        default="http://host.docker.internal:11434",
        description="Ollama 服务地址（用于 Chat LLM）",
        alias="AGENT_OLLAMA_BASE_URL",
    )

    # Downstream services
    cp_base_url: str = Field(
        default="http://localhost:8080",
        description="Base URL for ControlPlane HTTP API (e.g. http://cp:8080)",
        alias="AGENT_CP_BASE_URL",
    )
    request_timeout_sec: float = Field(
        default=30.0,
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

    # RAG / 知识库：PostgreSQL + pgvector
    rag_pg_dsn: Optional[str] = Field(
        default=None,
        description=(
            "知识库向量存储 DSN，例如 postgresql://cv_kb:cv_kb_pass@pgvector:5432/cv_kb；"
            "若未设置则使用 rag_pg_host 等字段拼接。"
        ),
        alias="AGENT_RAG_PG_DSN",
    )
    rag_pg_host: str = Field(
        default="pgvector",
        description="知识库向量存储 PostgreSQL 主机名（Docker 默认 pgvector）",
        alias="AGENT_RAG_PG_HOST",
    )
    rag_pg_port: int = Field(
        default=5432,
        description="知识库向量存储 PostgreSQL 端口",
        alias="AGENT_RAG_PG_PORT",
    )
    rag_pg_db: str = Field(
        default="cv_kb",
        description="知识库向量存储数据库名",
        alias="AGENT_RAG_PG_DB",
    )
    rag_pg_user: str = Field(
        default="cv_kb",
        description="知识库向量存储用户名",
        alias="AGENT_RAG_PG_USER",
    )
    rag_pg_password: str = Field(
        default="cv_kb_pass",
        description="知识库向量存储密码",
        alias="AGENT_RAG_PG_PASSWORD",
    )

    # RAG embedding 提供方：openai 或 ollama
    rag_embedding_provider: str = Field(
        default="openai",
        description="向量嵌入提供方：openai 或 ollama",
        alias="AGENT_RAG_EMBEDDING_PROVIDER",
    )
    rag_ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama 服务地址（用于 embedding）",
        alias="AGENT_RAG_OLLAMA_BASE_URL",
    )
    rag_ollama_model: str = Field(
        default="nomic-embed-text",
        description="Ollama embedding 模型名称",
        alias="AGENT_RAG_OLLAMA_MODEL",
    )

    # Service behaviour
    log_level: str = Field(
        default="INFO",
        description="Log level for the agent service",
        alias="AGENT_LOG_LEVEL",
    )

    # Excel / DataFrame 分析相关配置
    excel_file_base_dir: str = Field(
        default="",
        description="Excel 文件查找的基础目录，留空则直接使用 file_id 作为路径",
        alias="AGENT_EXCEL_FILE_BASE_DIR",
    )
    excel_df_cache_max_items: int = Field(
        default=16,
        description="进程内 DataFrame 缓存的最大条目数（<=0 表示不限制）",
        alias="AGENT_EXCEL_DF_CACHE_MAX_ITEMS",
    )
    excel_df_cache_ttl_sec: int = Field(
        default=1800,
        description="DataFrame 缓存条目的生存时间（秒，<=0 表示不过期）",
        alias="AGENT_EXCEL_DF_CACHE_TTL_SEC",
    )
    excel_max_chart_rows: int = Field(
        default=500,
        description="单个图表允许返回的最大数据行数，超过时需要聚合或抽样",
        alias="AGENT_EXCEL_MAX_CHART_ROWS",
    )

    # LangGraph recursion limit（用于防止 agent→tools 循环过深）
    recursion_limit: int = Field(
        default=12,
        description="StateGraph 执行的最大递归步数（recursion_limit）",
        alias="AGENT_RECURSION_LIMIT",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide Settings instance."""

    return Settings()  # type: ignore[call-arg]
