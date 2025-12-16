# RAG Service Configuration
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """RAG服务配置"""
    
    # 服务配置
    app_name: str = "RAG Knowledge Base Service"
    api_prefix: str = "/api"
    debug: bool = False
    
    # MySQL配置（元数据存储）
    mysql_host: str = Field(default="mysql", description="MySQL主机")
    mysql_port: int = Field(default=3306, description="MySQL端口")
    mysql_user: str = Field(default="root", description="MySQL用户名")
    mysql_password: str = Field(default="123456", description="MySQL密码")
    mysql_database: str = Field(default="rag_kb", description="MySQL数据库名")
    
    @property
    def mysql_dsn(self) -> str:
        return f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
    
    # pgvector配置（向量存储）
    pgvector_host: str = Field(default="pgvector", description="pgvector主机")
    pgvector_port: int = Field(default=5432, description="pgvector端口")
    pgvector_user: str = Field(default="cv_kb", description="pgvector用户")
    pgvector_password: str = Field(default="cv_kb_pass", description="pgvector密码")
    pgvector_database: str = Field(default="cv_kb", description="pgvector数据库")
    vector_dimension: int = Field(default=1024, description="向量维度(bge-m3)")
    
    @property
    def pgvector_dsn(self) -> str:
        return f"postgresql+psycopg://{self.pgvector_user}:{self.pgvector_password}@{self.pgvector_host}:{self.pgvector_port}/{self.pgvector_database}"
    
    # MinIO配置（文件存储）
    minio_endpoint: str = Field(default="minio:9000", description="MinIO端点")
    minio_access_key: str = Field(default="minioadmin", description="MinIO访问密钥")
    minio_secret_key: str = Field(default="minioadmin123", description="MinIO密钥")
    minio_bucket: str = Field(default="rag-documents", description="文档存储桶")
    minio_secure: bool = Field(default=False, description="是否使用HTTPS")
    
    # Ollama配置（LLM/Embedding）
    ollama_base_url: str = Field(
        default="http://host.docker.internal:11434",
        description="Ollama服务地址"
    )
    embedding_model: str = Field(
        default="bge-m3:567m",
        description="Embedding模型"
    )
    llm_model: str = Field(
        default="qwen3:30b",
        description="LLM模型用于问答"
    )
    
    # 文档处理配置
    chunk_size: int = Field(default=500, description="分块大小(字符)")
    chunk_overlap: int = Field(default=50, description="分块重叠(字符)")
    max_file_size: int = Field(default=50 * 1024 * 1024, description="最大文件大小(50MB)")
    
    # 网页抓取配置
    web_crawl_timeout: int = Field(default=30, description="网页抓取超时(秒)")
    
    class Config:
        env_prefix = "RAG_"
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
