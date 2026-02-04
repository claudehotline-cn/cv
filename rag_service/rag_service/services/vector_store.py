"""向量存储服务 - pgvector"""

import logging
import json
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass, field

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
    parent_id: Optional[int] = None  # 如果是子块，指向父块的数据库ID


class VectorStore:
    """pgvector向量存储"""
    
    
    def store_vectors(
        self,
        document_id: int,
        chunks: List[Tuple[int, str, List[float], dict]],
    ) -> int:
        """存储向量 (标准模式，非父子)"""
        if not chunks:
            return 0
        
        # 延迟导入jieba，避免启动慢
        import jieba
        
        with get_pgvector_session() as session:
            for chunk_index, content, embedding, metadata in chunks:
                # 分词 (for keyword search)
                words = jieba.cut_for_search(content)
                segmented_content = " ".join(words)
                
                # 构建向量字面量 - pgvector格式
                emb_literal = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
                meta_json = json.dumps(metadata, ensure_ascii=False)
                
                # 转义
                content_escaped = content.replace("'", "''").replace(":", r"\:")
                seg_content_escaped = segmented_content.replace("'", "''").replace(":", r"\:")
                meta_escaped = meta_json.replace("'", "''").replace(":", r"\:")
                
                # 插入 (同时写入 content_ts, is_parent=FALSE)
                sql = f"""
                    INSERT INTO rag_vectors (document_id, chunk_index, content, embedding, metadata, content_ts, is_parent)
                    VALUES (
                        {document_id}, 
                        {chunk_index}, 
                        '{content_escaped}', 
                        '{emb_literal}'::vector, 
                        '{meta_escaped}'::jsonb,
                        to_tsvector('simple', '{seg_content_escaped}'),
                        FALSE
                    )
                """
                session.execute(text(sql))
            
            session.commit()
        
        logger.info(f"Stored {len(chunks)} vectors for document {document_id}")
        return len(chunks)

    def store_hierarchical_vectors(
        self,
        document_id: int,
        parent_chunks: List[Tuple[int, str, List[float], dict]],
        child_chunks: List[Tuple[int, str, List[float], dict, int]],  # 最后一个是 parent_index
    ) -> Dict[int, int]:
        """
        存储父子向量
        
        Args:
            document_id: 文档ID
            parent_chunks: [(index, content, embedding, metadata), ...]
            child_chunks: [(index, content, embedding, metadata, parent_index), ...]
        
        Returns:
            parent_index_to_db_id: 映射 {parent_index: database_id}
        """
        import jieba
        
        parent_index_to_db_id = {}
        
        with get_pgvector_session() as session:
            # 1. 存储父块
            for chunk_index, content, embedding, metadata in parent_chunks:
                words = jieba.cut_for_search(content)
                segmented_content = " ".join(words)
                
                emb_literal = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
                meta_json = json.dumps(metadata, ensure_ascii=False)
                
                content_escaped = content.replace("'", "''").replace(":", r"\:")
                seg_content_escaped = segmented_content.replace("'", "''").replace(":", r"\:")
                meta_escaped = meta_json.replace("'", "''").replace(":", r"\:")
                
                sql = f"""
                    INSERT INTO rag_vectors (document_id, chunk_index, content, embedding, metadata, content_ts, is_parent, parent_id)
                    VALUES (
                        {document_id}, 
                        {chunk_index}, 
                        '{content_escaped}', 
                        '{emb_literal}'::vector, 
                        '{meta_escaped}'::jsonb,
                        to_tsvector('simple', '{seg_content_escaped}'),
                        TRUE,
                        NULL
                    )
                    RETURNING id
                """
                result = session.execute(text(sql))
                db_id = result.fetchone()[0]
                parent_index_to_db_id[chunk_index] = db_id
            
            # 2. 存储子块 (关联父块ID)
            for chunk_index, content, embedding, metadata, parent_index in child_chunks:
                parent_db_id = parent_index_to_db_id.get(parent_index)
                
                words = jieba.cut_for_search(content)
                segmented_content = " ".join(words)
                
                emb_literal = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
                meta_json = json.dumps(metadata, ensure_ascii=False)
                
                content_escaped = content.replace("'", "''").replace(":", r"\:")
                seg_content_escaped = segmented_content.replace("'", "''").replace(":", r"\:")
                meta_escaped = meta_json.replace("'", "''").replace(":", r"\:")
                
                parent_id_sql = f"{parent_db_id}" if parent_db_id else "NULL"
                
                sql = f"""
                    INSERT INTO rag_vectors (document_id, chunk_index, content, embedding, metadata, content_ts, is_parent, parent_id)
                    VALUES (
                        {document_id}, 
                        {chunk_index}, 
                        '{content_escaped}', 
                        '{emb_literal}'::vector, 
                        '{meta_escaped}'::jsonb,
                        to_tsvector('simple', '{seg_content_escaped}'),
                        FALSE,
                        {parent_id_sql}
                    )
                """
                session.execute(text(sql))
            
            session.commit()
        
        total = len(parent_chunks) + len(child_chunks)
        logger.info(f"Stored {total} hierarchical vectors ({len(parent_chunks)} parents, {len(child_chunks)} children) for doc {document_id}")
        return parent_index_to_db_id

    def get_parent_content(self, parent_db_id: int) -> Optional[str]:
        """根据数据库ID获取父块内容"""
        with get_pgvector_session() as session:
            result = session.execute(text(f"SELECT content FROM rag_vectors WHERE id = {parent_db_id}"))
            row = result.fetchone()
            return row[0] if row else None

    def get_parents_by_ids(self, parent_db_ids: List[int]) -> Dict[int, str]:
        """批量获取父块内容"""
        if not parent_db_ids:
            return {}
        ids_str = ",".join(str(i) for i in parent_db_ids)
        with get_pgvector_session() as session:
            result = session.execute(text(f"SELECT id, content FROM rag_vectors WHERE id IN ({ids_str})"))
            return {row[0]: row[1] for row in result}
    
    def search(
        self,
        query_embedding: List[float],
        knowledge_base_id: Optional[int] = None,
        top_k: int = 5,
    ) -> List[SearchResult]:
        """向量相似度搜索 (只搜索子块或普通块)"""
        emb_literal = "[" + ",".join(f"{x:.6f}" for x in query_embedding) + "]"
        
        doc_filter_sql = ""
        if knowledge_base_id is not None:
            doc_ids = self._get_kb_doc_ids(knowledge_base_id)
            if not doc_ids:
                return []
            doc_ids_str = ",".join(str(d) for d in doc_ids)
            doc_filter_sql = f"AND document_id IN ({doc_ids_str})"
        
        with get_pgvector_session() as session:
            # 只搜索非父块 (is_parent = FALSE OR is_parent IS NULL)
            sql = f"""
                SELECT 
                    id,
                    document_id,
                    chunk_index,
                    content,
                    1 - (embedding <=> '{emb_literal}'::vector) as score,
                    metadata,
                    parent_id
                FROM rag_vectors
                WHERE (is_parent = FALSE OR is_parent IS NULL)
                {doc_filter_sql}
                ORDER BY embedding <=> '{emb_literal}'::vector
                LIMIT {top_k}
            """
            
            result = session.execute(text(sql))
            return self._rows_to_results_with_parent(result)

    def search_keyword(
        self,
        query: str,
        knowledge_base_id: Optional[int] = None,
        top_k: int = 5,
    ) -> List[SearchResult]:
        """全文关键词搜索 (只搜索子块)"""
        import jieba
        import re
        
        # 分词并过滤空白/纯标点 token (避免 to_tsquery 语法错误)
        keywords = [k.strip() for k in jieba.cut_for_search(query) if k and k.strip()]
        keywords = [k for k in keywords if re.search(r"[0-9A-Za-z\u4e00-\u9fff]", k)]
        if not keywords:
            return []

        # Use plainto_tsquery for safety; treat keywords as plain terms.
        query_text = " ".join(keywords)

        doc_ids = None
        if knowledge_base_id is not None:
            doc_ids = self._get_kb_doc_ids(knowledge_base_id)
            if not doc_ids:
                return []
            
        with get_pgvector_session() as session:
            sql = text(
                """
                SELECT
                    id,
                    document_id,
                    chunk_index,
                    content,
                    ts_rank_cd(content_ts, query_ts) as score,
                    metadata,
                    parent_id
                FROM rag_vectors, plainto_tsquery('simple', :q) query_ts
                WHERE content_ts @@ query_ts
                AND (is_parent = FALSE OR is_parent IS NULL)
                AND (:doc_ids_is_null OR document_id = ANY(:doc_ids))
                ORDER BY score DESC
                LIMIT :limit
                """
            )

            params = {
                "q": query_text,
                "limit": int(top_k),
                "doc_ids_is_null": doc_ids is None,
                "doc_ids": doc_ids if doc_ids is not None else [],
            }
            try:
                result = session.execute(sql, params)
                return self._rows_to_results_with_parent(result)
            except Exception as e:
                logger.warning(f"Keyword search failed, falling back to empty: {e}")
                return []

    def _get_kb_doc_ids(self, kb_id: int) -> List[int]:
        from ..database import MySQLSessionLocal
        from ..models import Document
        mysql_db = MySQLSessionLocal()
        try:
            docs = mysql_db.query(Document).filter(
                Document.knowledge_base_id == kb_id
            ).all()
            return [d.id for d in docs]
        finally:
            mysql_db.close()

    def _rows_to_results(self, result) -> List[SearchResult]:
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

    def _rows_to_results_with_parent(self, result) -> List[SearchResult]:
        results = []
        for row in result:
            results.append(SearchResult(
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                content=row.content,
                score=float(row.score),
                metadata=row.metadata if isinstance(row.metadata, dict) else json.loads(row.metadata or "{}"),
                parent_id=row.parent_id,
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

    def store_image_vectors(
        self, 
        document_id: int, 
        images: List[Tuple[int, str, List[float], str, dict]]
    ) -> int:
        """
        存储图像向量
        
        Args:
            document_id: 文档ID
            images: [(image_index, image_path, embedding, description, metadata), ...]
        """
        if not images:
            return 0

        # 统一走 rag_vectors（与文本向量同表），通过 metadata.type='image' 区分。
        chunks = []
        for image_index, image_path, embedding, description, metadata in images:
            meta = dict(metadata or {})
            meta.setdefault("type", "image")
            meta.setdefault("minio_path", image_path)
            chunks.append((image_index, description, embedding, meta))

        stored = self.store_vectors(document_id=document_id, chunks=chunks)
        logger.info(f"Stored {stored} image vectors for document {document_id}")
        return stored

    def search_images(
        self,
        query_embedding: List[float],
        knowledge_base_id: Optional[int] = None,
        top_k: int = 5,
    ) -> List[dict]:
        """图像向量检索 (在 rag_vectors 中按 metadata.type 过滤)"""
        emb_literal = "[" + ",".join(f"{x:.6f}" for x in query_embedding) + "]"

        doc_filter_sql = ""
        if knowledge_base_id is not None:
            doc_ids = self._get_kb_doc_ids(knowledge_base_id)
            if not doc_ids:
                return []
            doc_ids_str = ",".join(str(d) for d in doc_ids)
            doc_filter_sql = f"AND document_id IN ({doc_ids_str})"

        with get_pgvector_session() as session:
            sql = f"""
                SELECT 
                    id,
                    document_id,
                    chunk_index,
                    content as description,
                    metadata,
                    1 - (embedding <=> '{emb_literal}'::vector) as score
                FROM rag_vectors
                WHERE (is_parent = FALSE OR is_parent IS NULL)
                AND (metadata->>'type') = 'image'
                {doc_filter_sql}
                ORDER BY embedding <=> '{emb_literal}'::vector
                LIMIT {top_k}
            """

            result = session.execute(text(sql))

            # 批量补齐 image_path/filename（来自 MySQL rag_documents）
            rows = list(result)
            doc_ids = sorted({int(r.document_id) for r in rows})
            doc_map = {}
            if doc_ids:
                try:
                    from ..database import MySQLSessionLocal
                    from ..models import Document
                    with MySQLSessionLocal() as mysql_db:
                        docs = mysql_db.query(Document).filter(Document.id.in_(doc_ids)).all()
                        doc_map = {d.id: d for d in docs}
                except Exception:
                    doc_map = {}

            out = []
            for row in rows:
                meta = row.metadata if isinstance(row.metadata, dict) else json.loads(row.metadata or "{}")
                doc = doc_map.get(int(row.document_id))
                image_path = meta.get("minio_path") or (doc.file_path if doc else None)
                out.append(
                    {
                        "id": row.id,
                        "document_id": row.document_id,
                        "image_index": row.chunk_index,
                        "image_path": image_path,
                        "description": row.description,
                        "metadata": meta,
                        "score": float(row.score),
                    }
                )

            return out
# 单例
vector_store = VectorStore()
