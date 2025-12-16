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
    document_count = Column(Integer, default=0, comment="文档数量")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    
    # 关联文档
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "embedding_model": self.embedding_model,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
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
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
