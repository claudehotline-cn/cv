"""Article Agent Configuration.

This module provides article-specific configuration and path helpers
built on top of agent_core.WorkspaceBackend.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings

from agent_core import WorkspaceBackend


# Agent name constant for this plugin
AGENT_NAME = "article_agent"


class Settings(BaseSettings):
    """Article Agent Configuration"""

    # Article-specific settings (not filesystem)
    articles_base_url: str = Field(
        default="/articles",
        alias="ARTICLE_AGENT_ARTICLES_BASE_URL",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def get_backend(session_id: str, task_id: Optional[str] = None, user_id: str = "default") -> WorkspaceBackend:
    """Get WorkspaceBackend instance for article_agent.
    
    Args:
        session_id: Session/article ID (article_id is used as session_id)
        task_id: Optional task ID for async tasks
        user_id: User identifier (default: "default")
        
    Returns:
        WorkspaceBackend configured for article_agent
    """
    # Strip prefix if present
    clean_id = session_id
    if clean_id.startswith("article_"):
        clean_id = clean_id[len("article_"):]
    
    return WorkspaceBackend(AGENT_NAME, user_id, clean_id, task_id)


__all__ = [
    "AGENT_NAME",
    "Settings",
    "get_settings",
    "get_backend",
]
