from functools import lru_cache
from typing import Dict, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration for the agent-langchain服务（DB/Excel 图表 Agent）。"""

    # LLM / provider settings
    llm_provider: str = Field(
        default="openai",
        description="LLM 提供方：openai | ollama | vllm",
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
    vllm_base_url: str = Field(
        default="http://vllm:8000/v1",
        description="vLLM OpenAI-compatible API 地址",
        alias="AGENT_VLLM_BASE_URL",
    )

    # 数据库（MySQL）分析相关配置
    db_host: str = Field(
        default="mysql",
        description="用于数据分析的 MySQL 主机名（通常为 Docker 服务名）",
        alias="AGENT_DB_HOST",
    )
    db_port: int = Field(
        default=3306,
        description="用于数据分析的 MySQL 端口",
        alias="AGENT_DB_PORT",
    )
    db_user: str = Field(
        default="root",
        description="用于数据分析的 MySQL 用户名",
        alias="AGENT_DB_USER",
    )
    db_password: str = Field(
        default="123456",
        description="用于数据分析的 MySQL 密码",
        alias="AGENT_DB_PASSWORD",
    )
    db_default_name: str = Field(
        default="cv_cp",
        description="默认用于数据分析的数据库名；请求未显式指定时使用",
        alias="AGENT_DB_DEFAULT_NAME",
    )
    db_extra_databases: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "额外数据源别名到数据库名的映射，例如 {'reporting': 'cv_reporting'}；"
            "当请求中的 db_name 与某个别名匹配时，将被映射为实际数据库名。"
        ),
        alias="AGENT_DB_EXTRA_DATABASES",
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

    # LLM 与 HTTP 超时时间
    request_timeout_sec: float = Field(
        default=30.0,
        description="默认的 LLM/HTTP 超时时间（秒）",
        alias="AGENT_REQUEST_TIMEOUT",
    )
    db_sql_timeout_sec: float = Field(
        default=60.0,
        description="SQL Agent 生成数据库查询 SQL 的超时时间（秒），覆盖通用 request_timeout_sec",
        alias="AGENT_DB_SQL_TIMEOUT_SEC",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程内唯一 Settings 实例。"""

    return Settings()  # type: ignore[call-arg]

