"""数据库模型定义"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class KnowledgeBase(Base):
    """知识库模型"""
    __tablename__ = "rag_knowledge_bases"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(36), nullable=True, index=True, comment="租户ID")
    name = Column(String(255), nullable=False, unique=True, comment="知识库名称")
    description = Column(Text, nullable=True, comment="知识库描述")
    embedding_model = Column(String(100), default="bge-m3:567m", comment="Embedding模型")
    chunk_size = Column(Integer, default=500, comment="分块大小")
    chunk_overlap = Column(Integer, default=50, comment="分块重叠")
    cleaning_rules = Column(Text, nullable=True, comment="清洗规则(JSON)")
    document_count = Column(Integer, default=0, comment="文档数量")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    
    # 关联文档
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")
    
    def to_dict(self) -> dict:
        import json as _json
        rules = None
        if self.cleaning_rules:
            try:
                rules = _json.loads(self.cleaning_rules)
            except Exception:
                rules = None
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "description": self.description,
            "embedding_model": self.embedding_model,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "cleaning_rules": rules,
            "document_count": self.document_count,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Document(Base):
    """文档模型"""
    __tablename__ = "rag_documents"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(36), nullable=True, index=True, comment="租户ID")
    knowledge_base_id = Column(Integer, ForeignKey("rag_knowledge_bases.id"), nullable=False)
    filename = Column(String(500), nullable=False, comment="文件名")
    file_type = Column(String(50), nullable=False, comment="文件类型")
    file_size = Column(Integer, default=0, comment="文件大小(bytes)")
    file_path = Column(String(1000), nullable=True, comment="MinIO存储路径")
    source_url = Column(String(2000), nullable=True, comment="来源URL(网页导入)")
    chunk_count = Column(Integer, default=0, comment="分块数量")
    status = Column(String(50), default="pending", comment="处理状态: pending/processing/completed/failed")
    error_message = Column(Text, nullable=True, comment="错误信息")
    graph_built = Column(Boolean, default=False, comment="是否已构建图谱")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    
    # 关联知识库
    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "knowledge_base_id": self.knowledge_base_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "file_path": self.file_path,
            "source_url": self.source_url,
            "chunk_count": self.chunk_count,
            "status": self.status,
            "error_message": self.error_message,
            "graph_built": self.graph_built,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DocumentOutline(Base):
    """文档结构大纲（用于 UI Outline，不依赖 chunk 展示逻辑）"""

    __tablename__ = "rag_document_outlines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(36), nullable=True, index=True, comment="租户ID")
    knowledge_base_id = Column(Integer, ForeignKey("rag_knowledge_bases.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("rag_documents.id"), nullable=False, unique=True, index=True)
    extraction = Column(String(50), nullable=True)  # marker|pdfplumber|...
    outline_json = Column(Text, nullable=True)  # JSON tree
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def to_dict(self) -> dict:
        import json as _json

        outline = None
        if self.outline_json:
            try:
                outline = _json.loads(self.outline_json)
            except Exception:
                outline = None

        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "knowledge_base_id": self.knowledge_base_id,
            "document_id": self.document_id,
            "extraction": self.extraction,
            "outline": outline,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ========== 多媒体模型 ==========

class DocumentImage(Base):
    """文档图片模型"""
    __tablename__ = "rag_document_images"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("rag_documents.id"), nullable=False, index=True)
    image_index = Column(Integer, default=0, comment="图片在文档中的索引")
    image_path = Column(String(1000), nullable=True, comment="MinIO存储路径")
    description = Column(Text, nullable=True, comment="VLM生成的图片描述")
    width = Column(Integer, default=0, comment="图片宽度")
    height = Column(Integer, default=0, comment="图片高度")
    page_number = Column(Integer, nullable=True, comment="所在页码(PDF)")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "image_index": self.image_index,
            "image_path": self.image_path,
            "description": self.description,
            "width": self.width,
            "height": self.height,
            "page_number": self.page_number,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DocumentAudio(Base):
    """文档音频模型"""
    __tablename__ = "rag_document_audios"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("rag_documents.id"), nullable=False, index=True)
    audio_path = Column(String(1000), nullable=True, comment="MinIO存储路径")
    transcript = Column(Text, nullable=True, comment="音频转写文本")
    language = Column(String(20), nullable=True, comment="检测到的语言")
    duration = Column(Integer, default=0, comment="音频时长(秒)")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "audio_path": self.audio_path,
            "transcript": self.transcript,
            "language": self.language,
            "duration": self.duration,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DocumentVideo(Base):
    """文档视频模型"""
    __tablename__ = "rag_document_videos"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("rag_documents.id"), nullable=False, index=True)
    video_path = Column(String(1000), nullable=True, comment="MinIO存储路径")
    summary = Column(Text, nullable=True, comment="视频内容摘要")
    transcript = Column(Text, nullable=True, comment="视频音频转写")
    duration = Column(Integer, default=0, comment="视频时长(秒)")
    width = Column(Integer, default=0, comment="视频宽度")
    height = Column(Integer, default=0, comment="视频高度")
    frame_count = Column(Integer, default=0, comment="分析的帧数")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "video_path": self.video_path,
            "summary": self.summary,
            "transcript": self.transcript,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "frame_count": self.frame_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ========== 会话历史模型 ==========

class ChatSession(Base):
    """对话会话"""
    __tablename__ = "rag_chat_sessions"
    
    id = Column(String(36), primary_key=True, comment="UUID")
    tenant_id = Column(String(36), nullable=True, index=True, comment="租户ID")
    knowledge_base_id = Column(Integer, ForeignKey("rag_knowledge_bases.id"), nullable=True, index=True)
    title = Column(String(255), nullable=True, comment="会话标题")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "knowledge_base_id": self.knowledge_base_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatMessage(Base):
    """对话消息（支持多模态）"""
    __tablename__ = "rag_chat_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("rag_chat_sessions.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False, comment="角色: user/assistant")
    content = Column(Text, nullable=True, comment="文本内容")
    image_paths = Column(Text, nullable=True, comment="JSON数组: MinIO图片路径")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    
    session = relationship("ChatSession", back_populates="messages")
    
    def to_dict(self) -> dict:
        import json as _json
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "image_paths": _json.loads(self.image_paths) if self.image_paths else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ========== RAG Eval / Benchmarks ==========


class EvalDataset(Base):
    """评测数据集（按 KB 隔离）"""

    __tablename__ = "rag_eval_datasets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(36), nullable=True, index=True, comment="租户ID")
    knowledge_base_id = Column(Integer, ForeignKey("rag_knowledge_bases.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_by = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cases = relationship("EvalCase", back_populates="dataset", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "knowledge_base_id": self.knowledge_base_id,
            "name": self.name,
            "description": self.description,
            "created_by": self.created_by,
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EvalCase(Base):
    """评测用例（query + 期望来源）"""

    __tablename__ = "rag_eval_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(Integer, ForeignKey("rag_eval_datasets.id"), nullable=False, index=True)
    query = Column(Text, nullable=False)
    expected_sources = Column(Text, nullable=True)  # JSON list[str]
    notes = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)  # JSON list[str]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    dataset = relationship("EvalDataset", back_populates="cases")

    def to_dict(self) -> dict:
        import json as _json

        def _load_list(raw: str | None):
            if not raw:
                return []
            try:
                val = _json.loads(raw)
                return val if isinstance(val, list) else []
            except Exception:
                return []

        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "query": self.query,
            "expected_sources": _load_list(self.expected_sources),
            "notes": self.notes,
            "tags": _load_list(self.tags),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BenchmarkRun(Base):
    """Benchmark Run 元数据（按 KB + Dataset）"""

    __tablename__ = "rag_benchmark_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(36), nullable=True, index=True, comment="租户ID")
    knowledge_base_id = Column(Integer, ForeignKey("rag_knowledge_bases.id"), nullable=False, index=True)
    dataset_id = Column(Integer, ForeignKey("rag_eval_datasets.id"), nullable=False, index=True)
    mode = Column(String(20), nullable=False)  # vector|graph
    top_k = Column(Integer, default=5)
    status = Column(String(20), default="queued")  # queued|running|succeeded|failed
    created_by = Column(String(255), nullable=True)
    request_id = Column(String(36), nullable=True, index=True)  # UUID for audit correlation
    metrics = Column(Text, nullable=True)  # JSON
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    results = relationship("BenchmarkCaseResult", back_populates="run", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        import json as _json

        metrics = None
        if self.metrics:
            try:
                metrics = _json.loads(self.metrics)
            except Exception:
                metrics = None

        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "knowledge_base_id": self.knowledge_base_id,
            "dataset_id": self.dataset_id,
            "mode": self.mode,
            "top_k": self.top_k,
            "status": self.status,
            "created_by": self.created_by,
            "request_id": self.request_id,
            "metrics": metrics,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }


class BenchmarkCaseResult(Base):
    """逐 case 结果"""

    __tablename__ = "rag_benchmark_case_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("rag_benchmark_runs.id"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("rag_eval_cases.id"), nullable=False, index=True)
    hit_rank = Column(Integer, nullable=True)
    mrr = Column(Float, default=0.0)
    ndcg = Column(Float, default=0.0)
    retrieved = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("BenchmarkRun", back_populates="results")

    def to_dict(self) -> dict:
        import json as _json

        retrieved = None
        if self.retrieved:
            try:
                retrieved = _json.loads(self.retrieved)
            except Exception:
                retrieved = None

        return {
            "id": self.id,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "hit_rank": self.hit_rank,
            "mrr": float(self.mrr or 0.0),
            "ndcg": float(self.ndcg or 0.0),
            "retrieved": retrieved,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EvalCaseExpectation(Base):
    """评测用例期望（单独表，避免改动已有 rag_eval_cases 结构）"""

    __tablename__ = "rag_eval_case_expectations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("rag_eval_cases.id"), nullable=False, unique=True, index=True)
    expected_answer = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "expected_answer": self.expected_answer,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BenchmarkQaResult(Base):
    """Answer-level 评测结果（按 run/case 存储生成答案与评分）"""

    __tablename__ = "rag_benchmark_qa_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("rag_benchmark_runs.id"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("rag_eval_cases.id"), nullable=False, index=True)
    expected_answer = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)
    score = Column(Float, nullable=True)
    judge = Column(Text, nullable=True)  # JSON
    sources = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        import json as _json

        judge = None
        if self.judge:
            try:
                judge = _json.loads(self.judge)
            except Exception:
                judge = None

        sources = None
        if self.sources:
            try:
                sources = _json.loads(self.sources)
            except Exception:
                sources = None

        return {
            "id": self.id,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "expected_answer": self.expected_answer,
            "answer": self.answer,
            "score": float(self.score) if self.score is not None else None,
            "judge": judge,
            "sources": sources,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
