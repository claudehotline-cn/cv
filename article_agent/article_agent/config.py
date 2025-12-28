from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """article_agent 全局配置。"""

    llm_provider: Literal["openai", "ollama", "siliconflow", "gemini"] = Field(
        default="ollama",
        description="LLM 提供方：openai、ollama、siliconflow 或 gemini。默认使用本地 Ollama。",
        alias="ARTICLE_AGENT_LLM_PROVIDER",
    )
    llm_model: str = Field(
        default="qwen3:30b",
        description="默认对话 / 推理模型名称（在 Ollama 场景下默认为 qwen3:30b）。",
        alias="ARTICLE_AGENT_LLM_MODEL",
    )
    openai_api_key: Optional[str] = Field(
        default=None,
        description="OpenAI 或兼容服务的 API Key。",
        alias="OPENAI_API_KEY",
    )
    ollama_base_url: str = Field(
        default="http://host.docker.internal:11434",
        description="Ollama 服务地址。",
        alias="ARTICLE_AGENT_OLLAMA_BASE_URL",
    )
    ollama_num_predict: int = Field(
        default=24576,
        description="Ollama 生成最大 token 数（num_predict）。",
        alias="ARTICLE_AGENT_OLLAMA_NUM_PREDICT",
    )
    ollama_num_ctx: int = Field(
        default=32768,
        description="Ollama 上下文窗口大小（num_ctx）。",
        alias="ARTICLE_AGENT_OLLAMA_NUM_CTX",
    )

    # VLM 配置（用于图片理解）
    vlm_enabled: bool = Field(
        default=True,
        description="是否启用 VLM 图片理解（在 Researcher 阶段分析候选图片）。",
        alias="ARTICLE_AGENT_VLM_ENABLED",
    )
    vlm_model: str = Field(
        default="qwen3-vl:30b",
        description="VLM 模型名称（用于图片内容理解）。",
        alias="ARTICLE_AGENT_VLM_MODEL",
    )

    # SiliconFlow（硅基流动）配置
    siliconflow_api_key: Optional[str] = Field(
        default=None,
        description="SiliconFlow API Key。",
        alias="SILICONFLOW_API_KEY",
    )
    siliconflow_base_url: str = Field(
        default="https://api.siliconflow.cn/v1",
        description="SiliconFlow OpenAI 兼容 API 的基础地址。",
        alias="SILICONFLOW_BASE_URL",
    )

    # Google Gemini 配置
    google_api_key: Optional[str] = Field(
        default=None,
        description="Google AI Studio API Key（用于 Gemini 模型）。",
        alias="GOOGLE_API_KEY",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash-preview-05-20",
        description="Gemini 模型名称。",
        alias="ARTICLE_AGENT_GEMINI_MODEL",
    )

    outputs_dir: str = Field(
        default="/data/outputs",
        description="输出根目录",
        alias="ARTICLE_AGENT_OUTPUTS_DIR",
    )
    artifacts_dir: str = Field(
        default="/data/outputs/artifacts",
        description="中间产物（元数据、JSON）存储目录。",
        alias="ARTICLE_AGENT_ARTIFACTS_DIR",
    )
    drafts_dir: str = Field(
        default="/data/outputs/artifacts/drafts",
        description="AI 写作的章节草稿 markdown 目录。",
        alias="ARTICLE_AGENT_DRAFTS_DIR",
    )
    
    # 兼容旧代码，将 temp_dir 指向 artifacts_dir
    temp_dir: str = Field(
        default="/data/outputs/artifacts",
        description="中间产物存储目录（已废弃，建议使用 artifacts_dir）。",
        alias="ARTICLE_TEMP_DIR",
    )
    articles_base_dir: str = Field(
        default="/data/outputs/articles",
        description="文章与资源文件的根目录。",
        alias="ARTICLE_AGENT_ARTICLES_BASE_DIR",
    )
    articles_base_url: str = Field(
        default="/articles",
        description="对外暴露文章与资源的 URL 前缀。",
        alias="ARTICLE_AGENT_ARTICLES_BASE_URL",
    )


    enable_doc_refiner: bool = Field(
        default=True,
        description="是否启用 Doc Refiner（通篇润色，带标题结构锁）。",
        alias="ARTICLE_AGENT_ENABLE_DOC_REFINER",
    )

    http_user_agent: str = Field(
        default="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
        description="抓取网页时使用的 User-Agent（部分站点会拒绝默认 python-requests）。",
        alias="ARTICLE_AGENT_HTTP_USER_AGENT",
    )
    http_timeout_sec: float = Field(
        default=20.0,
        description="抓取网页的 HTTP 超时（秒）。",
        alias="ARTICLE_AGENT_HTTP_TIMEOUT_SEC",
    )
    http_max_attempts: int = Field(
        default=3,
        description="抓取网页的最大尝试次数（用于应对临时网络/SSL 抖动）。",
        alias="ARTICLE_AGENT_HTTP_MAX_ATTEMPTS",
    )
    http_retry_backoff_sec: float = Field(
        default=0.6,
        description="抓取网页失败后的重试退避（秒，按 attempt 线性递增）。",
        alias="ARTICLE_AGENT_HTTP_RETRY_BACKOFF_SEC",
    )

    # 性能与并发配置
    max_worker_threads: int = Field(
        default=5,
        description="并行执行的最大线程数（用于 Section Writer 等）。",
        alias="ARTICLE_AGENT_MAX_WORKER_THREADS",
    )

    # 流程控制阈值
    max_research_rounds: int = Field(
        default=2,
        description="最大研究（补充资料）轮数。",
        alias="ARTICLE_AGENT_MAX_RESEARCH_ROUNDS",
    )
    max_rewrite_rounds: int = Field(
        default=2,
        description="最大重写（Writer Audit）轮数。",
        alias="ARTICLE_AGENT_MAX_REWRITE_ROUNDS",
    )

    # 质量检查阈值 (字符数)
    min_important_note_chars: int = Field(
        default=300,
        description="重要章节笔记的最小字符数（Research Audit）。",
        alias="ARTICLE_AGENT_MIN_IMPORTANT_NOTE_CHARS",
    )
    min_total_draft_chars: int = Field(
        default=3000,
        description="初稿总最小字符数（Writer Audit）。",
        alias="ARTICLE_AGENT_MIN_TOTAL_DRAFT_CHARS",
    )
    min_core_section_chars: int = Field(
        default=800,
        description="核心章节最小字符数。",
        alias="ARTICLE_AGENT_MIN_CORE_SECTION_CHARS",
    )
    min_normal_section_chars: int = Field(
        default=400,
        description="普通章节最小字符数。",
        alias="ARTICLE_AGENT_MIN_NORMAL_SECTION_CHARS",
    )

    # URL 抓取增强配置
    enable_playwright_fetch: bool = Field(
        default=False,
        description="是否启用 Playwright 抓取（用于 JS 渲染页面）。",
        alias="ARTICLE_AGENT_ENABLE_PLAYWRIGHT",
    )
    playwright_timeout_sec: int = Field(
        default=30,
        description="Playwright 页面加载超时（秒）。",
        alias="ARTICLE_AGENT_PLAYWRIGHT_TIMEOUT",
    )
    use_trafilatura: bool = Field(
        default=True,
        description="是否使用 trafilatura 提取正文（提升静态页面抓取质量）。",
        alias="ARTICLE_AGENT_USE_TRAFILATURA",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings"]
