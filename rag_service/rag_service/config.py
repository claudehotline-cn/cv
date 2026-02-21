# RAG Service Configuration
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from functools import lru_cache


DEFAULT_VLLM_MODEL = "/data/models/Qwen3-Omni-30B-A3B-Thinking-AWQ-4bit"


class Settings(BaseSettings):
    """RAG服务配置"""
    
    # 服务配置
    app_name: str = "RAG Knowledge Base Service"
    api_prefix: str = "/api"
    debug: bool = False

    # 后台任务/队列
    redis_url: str = Field(
        default="redis://langgraph-redis:6379",
        description="Redis URL (用于任务队列/缓存)"
    )
    queue_name: str = Field(
        default="rag:queue",
        description="ARQ 队列名称 (避免与其它服务共用默认 arq:queue 冲突)"
    )
    use_job_queue: bool = Field(
        default=True,
        description="是否使用任务队列执行耗时任务 (推荐生产启用)"
    )

    worker_max_jobs: int = Field(
        default=1,
        description="ARQ worker 并发执行的 job 数量 (max_jobs)"
    )
    
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
    vector_dimension: int = Field(default=1024, description="向量维度 (bge-m3)")
    
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
    
    # Ollama配置（仅用于 Embedding）
    ollama_base_url: str = Field(
        default="http://host.docker.internal:11434",
        description="Ollama服务地址 (Embedding)"
    )
    embedding_model: str = Field(
        default="bge-m3:567m",
        description="Embedding模型名称 (建议中英混合用 bge-m3)"
    )
    reranker_model: str = Field(
        default="BAAI/bge-reranker-base",
        description="重排序模型名称 (推荐使用支持多语言的模型)"
    )
    # vLLM OpenAI-compatible API (LLM/VLM)
    vllm_base_url: str = Field(
        default="http://vllm:8000/v1",
        description="vLLM OpenAI-compatible base URL (include /v1)"
    )
    vllm_api_key: str = Field(
        default="EMPTY",
        description="vLLM API key (not usually enforced, but kept for compatibility)"
    )

    llm_model: str = Field(
        default=DEFAULT_VLLM_MODEL,
        description="LLM 模型 (vLLM /v1/models id)"
    )
    llm_timeout_sec: int = Field(
        default=180,
        description="LLM 调用超时(秒)"
    )
    graph_llm_model: str = Field(
        default=DEFAULT_VLLM_MODEL,
        description="GraphRAG 抽取用 LLM 模型 (vLLM)"
    )
    graph_llm_timeout_sec: int = Field(
        default=120,
        description="GraphRAG 抽取 LLM 调用超时(秒)"
    )

    query_rewriter_model: str = Field(
        default=DEFAULT_VLLM_MODEL,
        description="Multi-query 扩展用 LLM 模型 (vLLM)"
    )
    query_rewriter_timeout_sec: int = Field(
        default=45,
        description="Multi-query 扩展超时(秒)"
    )

    # Auth integration
    auth_introspection_url: str = Field(
        default="http://agent-auth:8000/internal/introspect",
        description="Auth service introspection URL for bearer/api-key validation",
    )
    enable_context_compression: bool = Field(
        default=False,
        description="是否启用上下文压缩 (消耗额外LLM调用)"
    )
    
    # ========== 多模态配置 ==========
    
    # VLM 视觉语言模型配置
    vlm_model: str = Field(
        default=DEFAULT_VLLM_MODEL,
        description="VLM 模型 (vLLM /v1/models id)"
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

    pdf_extractor: str = Field(
        default="marker",
        description="PDF 解析模式: marker|pdfplumber|auto (默认 marker)"
    )

    pdf_marker_force_ocr: bool = Field(
        default=False,
        description="Marker/PDF 解析是否强制全量 OCR (一般不需要)"
    )
    pdf_marker_ocr_alphanum_threshold: float = Field(
        default=0.0,
        description="Marker OCR 触发阈值(字母数字比例); 中文 PDF 建议设低，避免误判乱码导致全量 OCR"
    )
    
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
