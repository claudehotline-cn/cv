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
    minio_bucket: str = Field(default="article", description="文档存储桶")
    minio_secure: bool = Field(default=False, description="是否使用HTTPS")

    # Neo4j配置（图数据库）
    neo4j_uri: str = Field(default="bolt://neo4j:7687", description="Neo4j BOLT地址")
    neo4j_user: str = Field(default="neo4j", description="Neo4j用户名")
    neo4j_password: str = Field(default="password", description="Neo4j密码")
    
    # Ollama配置（LLM/Embedding）
    ollama_base_url: str = Field(
        default="http://host.docker.internal:11434",
        description="Ollama服务地址"
    )
    embedding_model: str = Field(
        default="nomic-embed-text:latest",
        description="Embedding模型名称"
    )
    reranker_model: str = Field(
        default="BAAI/bge-reranker-base",
        description="重排序模型名称 (推荐使用支持多语言的模型)"
    )
    vector_dimension: int = Field(
        default=768,
        description="向量维度"
    )
    llm_model: str = Field(
        default="qwen3-vl:30b",
        description="LLM模型用于问答"
    )
    enable_context_compression: bool = Field(
        default=False,
        description="是否启用上下文压缩 (消耗额外LLM调用)"
    )
    
    # ========== 多模态配置 ==========
    
    # VLM 视觉语言模型配置
    vlm_model: str = Field(
        default="qwen3-vl:30b",
        description="视觉语言模型 (支持图像/视频理解)"
    )
    image_vector_dimension: int = Field(
        default=4096,
        description="图像向量维度"
    )
    max_image_size: int = Field(
        default=20 * 1024 * 1024,
        description="最大图片大小(20MB)"
    )
    supported_image_types: str = Field(
        default=".jpg,.jpeg,.png,.webp,.gif,.bmp",
        description="支持的图片格式"
    )
    
    # 语音配置 (Whisper)
    whisper_model: str = Field(
        default="large-v3",
        description="Whisper 模型 (tiny/base/small/medium/large-v3)"
    )
    whisper_device: str = Field(
        default="cuda",
        description="Whisper 运行设备 (cuda/cpu)"
    )
    supported_audio_types: str = Field(
        default=".mp3,.wav,.m4a,.flac,.ogg,.webm",
        description="支持的音频格式"
    )
    
    # 视频配置
    video_sample_interval: float = Field(
        default=1.0,
        description="视频抽帧间隔(秒) - 仅在VLM不支持原生视频时使用"
    )
    video_max_frames: int = Field(
        default=300,
        description="最大分析帧数"
    )
    supported_video_types: str = Field(
        default=".mp4,.webm,.avi,.mov,.mkv",
        description="支持的视频格式"
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
