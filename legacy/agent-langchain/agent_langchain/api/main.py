"""FastAPI Application Main Entry Point.

Agent Chat API 服务入口。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .presentation import chat_router, sessions_router

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

_LOGGER = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(
        title="Agent Chat API",
        description="自托管的 Agent Chat 服务，支持流式对话、思维链展示、HITL 交互。",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    
    # CORS 配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 注册路由
    app.include_router(sessions_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    
    @app.get("/health")
    async def health_check():
        """健康检查端点。"""
        return {"status": "healthy"}
    
    @app.on_event("startup")
    async def startup_event():
        """应用启动事件。"""
        _LOGGER.info("Agent Chat API starting up...")
    
    @app.on_event("shutdown")
    async def shutdown_event():
        """应用关闭事件。"""
        _LOGGER.info("Agent Chat API shutting down...")
    
    return app


# 创建应用实例
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "agent_langchain.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
