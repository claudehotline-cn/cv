"""API Configuration."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional


class Settings:
    """应用配置。"""
    
    # 数据库
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@pgvector:5432/langgraph"
    )
    
    # 存储模式
    use_memory_storage: bool = os.getenv("USE_MEMORY_STORAGE", "true").lower() == "true"
    
    # 服务器
    host: str = os.getenv("API_HOST", "0.0.0.0")
    port: int = int(os.getenv("API_PORT", "8000"))
    
    # CORS
    cors_origins: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例。"""
    return Settings()
