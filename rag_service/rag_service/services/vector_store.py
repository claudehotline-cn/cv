"""向量存储服务 - pgvector"""

import logging
import json
from typing import List, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_pgvector_session

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """检索结果"""
    document_id: int
    chunk_index: int
    content: str
    score: float
    metadata: dict


class VectorStore:
    """pgvector向量存储"""
    
    def store_vectors(
        self,
        document_id: int,
        chunks: List[Tuple[int, str, List[float], dict]],
    ) -> int:
        """存储向量
        
        Args:
            document_id: 文档ID
            chunks: [(chunk_index, content, embedding, metadata), ...]
        
        Returns:
            存储的向量数量
        """
        if not chunks:
            return 0
        
        with get_pgvector_session() as session:
            for chunk_index, content, embedding, metadata in chunks:
                # 构建向量字面量 - pgvector格式
                emb_literal = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
                meta_json = json.dumps(metadata, ensure_ascii=False)
                
                # 使用原生SQL避免参数绑定问题
                # 注意：content需要转义单引号
                # 同时需要将冒号转义为双冒号，防止SQLAlchemy将 :word 解析为绑定参数
                content_escaped = content.replace("'", "''").replace(":", r"\:")
                meta_escaped = meta_json.replace("'", "''").replace(":", r"\:")
                
                sql = f"""
                    INSERT INTO rag_vectors (document_id, chunk_index, content, embedding, metadata)
                    VALUES ({document_id}, {chunk_index}, '{content_escaped}', '{emb_literal}'::vector, '{meta_escaped}'::jsonb)
                """
                session.execute(text(sql))
            
            session.commit()
        
        logger.info(f"Stored {len(chunks)} vectors for document {document_id}")
        return len(chunks)
    
    def search(
        self,
        query_embedding: List[float],
        knowledge_base_id: Optional[int] = None,
        top_k: int = 5,
    ) -> List[SearchResult]:
        """向量相似度搜索
        
        Args:
            query_embedding: 查询向量
            knowledge_base_id: 限定知识库ID（可选）
            top_k: 返回结果数量
        
        Returns:
            检索结果列表
        """
        emb_literal = "[" + ",".join(f"{x:.6f}" for x in query_embedding) + "]"
        
        # 如果指定了知识库ID，先从MySQL获取该知识库的文档ID列表
        doc_ids = None
        if knowledge_base_id is not None:
            from ..database import MySQLSessionLocal
            from ..models import Document
            
            mysql_db = MySQLSessionLocal()
            try:
                docs = mysql_db.query(Document).filter(
                    Document.knowledge_base_id == knowledge_base_id
                ).all()
                doc_ids = [d.id for d in docs]
            finally:
                mysql_db.close()
            
            if not doc_ids:
                return []  # 该知识库没有文档
        
        with get_pgvector_session() as session:
            # 构建查询 - 使用原生SQL
            if doc_ids is not None:
                # 使用IN子句过滤文档ID
                doc_ids_str = ",".join(str(d) for d in doc_ids)
                sql = f"""
                    SELECT 
                        v.document_id,
                        v.chunk_index,
                        v.content,
                        1 - (v.embedding <=> '{emb_literal}'::vector) as score,
                        v.metadata
                    FROM rag_vectors v
                    WHERE v.document_id IN ({doc_ids_str})
                    ORDER BY v.embedding <=> '{emb_literal}'::vector
                    LIMIT {top_k}
                """
            else:
                sql = f"""
                    SELECT 
                        document_id,
                        chunk_index,
                        content,
                        1 - (embedding <=> '{emb_literal}'::vector) as score,
                        metadata
                    FROM rag_vectors
                    ORDER BY embedding <=> '{emb_literal}'::vector
                    LIMIT {top_k}
                """
            
            result = session.execute(text(sql))
            
            results = []
            for row in result:
                results.append(SearchResult(
                    document_id=row.document_id,
                    chunk_index=row.chunk_index,
                    content=row.content,
                    score=float(row.score),
                    metadata=row.metadata if isinstance(row.metadata, dict) else json.loads(row.metadata or "{}"),
                ))
            
            return results
    
    def delete_document_vectors(self, document_id: int) -> int:
        """删除文档的所有向量"""
        with get_pgvector_session() as session:
            result = session.execute(
                text(f"DELETE FROM rag_vectors WHERE document_id = {document_id}")
            )
            session.commit()
            deleted = result.rowcount
        
        logger.info(f"Deleted {deleted} vectors for document {document_id}")
        return deleted


# 单例
vector_store = VectorStore()
