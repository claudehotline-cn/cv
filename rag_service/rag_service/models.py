"""数据库模型定义"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class KnowledgeBase(Base):
    """知识库模型"""
    __tablename__ = "rag_knowledge_bases"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
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
    knowledge_base_id = Column(Integer, ForeignKey("rag_knowledge_bases.id"), nullable=True, index=True)
    title = Column(String(255), nullable=True, comment="会话标题")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
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
