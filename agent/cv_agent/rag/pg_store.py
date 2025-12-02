from functools import lru_cache
from typing import Any, Dict, List, Optional

import psycopg

from ..config import get_settings


@lru_cache(maxsize=1)
def _get_dsn() -> str:
    settings = get_settings()
    if settings.rag_pg_dsn:
        return settings.rag_pg_dsn
    return (
        f"postgresql://{settings.rag_pg_user}:{settings.rag_pg_password}"
        f"@{settings.rag_pg_host}:{settings.rag_pg_port}/{settings.rag_pg_db}"
    )


def get_connection() -> psycopg.Connection:
    """
    获取到知识库 PostgreSQL 的连接。

    注意：调用方负责关闭连接或使用上下文管理器。
    """

    dsn = _get_dsn()
    return psycopg.connect(dsn, autocommit=True)


def search_kb(
    collection: str,
    embedding: List[float],
    top_k: int = 5,
    *,
    module: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    在 kb_docs 表中按向量相似度搜索。

    期望表结构（由外部迁移/脚本创建）：

        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE IF NOT EXISTS kb_docs (
          id           BIGSERIAL PRIMARY KEY,
          collection   TEXT NOT NULL,
          doc_path     TEXT NOT NULL,
          doc_title    TEXT NOT NULL,
          chunk_index  INT  NOT NULL,
          content      TEXT NOT NULL,
          embedding    vector(1536) NOT NULL,
          module       TEXT,
          doc_type     TEXT,
          updated_at   TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_kb_docs_collection ON kb_docs(collection);
        CREATE INDEX IF NOT EXISTS idx_kb_docs_embedding
          ON kb_docs USING ivfflat (embedding vector_l2_ops);

    当前实现仅用于 Agent RAG 工具查询，不负责建表/写入。
    """

    if not embedding:
        return []

    # pgvector 兼容的向量字面量表示，如 '[0.1,0.2,...]'
    emb_literal = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"

    conditions = ["collection = %s"]
    params: List[Any] = [collection]

    if module is not None:
        conditions.append("module = %s")
        params.append(module)
    if doc_type is not None:
        conditions.append("doc_type = %s")
        params.append(doc_type)

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT
          id,
          doc_title,
          doc_path,
          chunk_index,
          content
        FROM kb_docs
        WHERE {where_clause}
        ORDER BY embedding <-> %s::vector
        LIMIT %s
    """

    results: List[Dict[str, Any]] = []
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (*params, emb_literal, top_k))
            for row in cur.fetchall():
                rid, title, path, idx, content = row
                results.append(
                    {
                        "id": rid,
                        "title": title,
                        "path": path,
                        "chunk_index": idx,
                        "content": content,
                    }
                )
    finally:
        conn.close()

    return results
