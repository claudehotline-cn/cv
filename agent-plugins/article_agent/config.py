from __future__ import annotations

import os
import contextvars
from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings

# ContextVar for task_id (defaults to 'main')
_TASK_ID_CTX = contextvars.ContextVar("task_id", default="main")

class Settings(BaseSettings):
    """Article Agent Configuration"""

    workspace_root: str = Field(
        default="/data/workspace",
        description="Root workspace directory",
        alias="WORKSPACE_ROOT",
    )
    
    # Keep legacy content settings
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

def set_current_task_id(task_id: str):
    """Set the current task ID for path generation."""
    _TASK_ID_CTX.set(task_id)

def get_current_task_id() -> str:
    return _TASK_ID_CTX.get()

def get_article_dir(article_id: str) -> str:
    """
    Get article artifacts directory.
    Path: /data/workspace/{session_id}/{task_id}/artifacts/article_{article_id}
    Assumes article_id == session_id.
    """
    settings = get_settings()
    task_id = get_current_task_id()
    
    # Strip prefix if present
    clean_id = article_id
    if clean_id.startswith("article_"):
        clean_id = clean_id[len("article_"):]
        
    return os.path.join(
        settings.workspace_root,
        clean_id,  # session_id
        task_id,   # task_id
        "artifacts", 
        f"article_{clean_id}"
    )

def get_drafts_dir(article_id: str) -> str:
    return os.path.join(get_article_dir(article_id), "drafts")

def get_final_article_dir(article_id: str) -> str:
    return os.path.join(get_article_dir(article_id), "article")

__all__ = [
    "Settings",
    "get_settings",
    "set_current_task_id",
    "get_current_task_id",
    "get_article_dir",
    "get_drafts_dir",
    "get_final_article_dir",
]
