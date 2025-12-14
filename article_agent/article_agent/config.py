from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """article_agent 全局配置。"""

    llm_provider: Literal["openai", "ollama", "siliconflow"] = Field(
        default="ollama",
        description="LLM 提供方：openai、ollama 或 siliconflow。默认使用本地 Ollama。",
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
        default=4096,
        description="Ollama 生成最大 token 数（num_predict）。",
        alias="ARTICLE_AGENT_OLLAMA_NUM_PREDICT",
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

    articles_base_dir: str = Field(
        default="/data/articles",
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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings"]
