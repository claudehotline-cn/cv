"""RAG Knowledge Base Service - FastAPI Main Entry"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_mysql_db, init_pgvector_db
from .api.routes import router

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    logger.info("Initializing databases...")
    try:
        init_mysql_db()
        init_pgvector_db()
        logger.info("Databases initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize databases: {e}")
        raise
    
    yield
    
    # 关闭时清理
    logger.info("Shutting down...")


# 创建应用
app = FastAPI(
    title=settings.app_name,
    description="RAG Knowledge Base Service - 支持多格式文档和网页内容导入的知识库系统",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router, prefix=settings.api_prefix)

# 挂载静态文件目录 (用于 Article Agent 图片)
# 映射 /data/workspace/artifacts 到 /api/artifacts
# 例如: /api/artifacts/article_123/corpus/pic.png -> /data/workspace/artifacts/article_123/corpus/pic.png
from fastapi.staticfiles import StaticFiles
import os

artifacts_dir = "/data/workspace/artifacts"
if not os.path.exists(artifacts_dir):
    os.makedirs(artifacts_dir, exist_ok=True)

app.mount("/api/artifacts", StaticFiles(directory=artifacts_dir), name="artifacts")


@app.get("/health")
def health_check():
    """健康检查"""
    return {"status": "healthy", "service": "rag-service"}


@app.get("/")
def root():
    """根路径"""
    return {
        "service": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8200)
