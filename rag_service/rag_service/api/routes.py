"""API路由定义"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl
from typing import List, Optional
import json
import tempfile
import os
import logging

from ..database import get_mysql_db, MySQLSessionLocal
from ..models import KnowledgeBase, Document
from ..models import DocumentOutline
from ..services.document_loader import document_loader
from ..services.web_crawler import web_crawler
from ..services.chunker import document_chunker
from ..services.embedder import embedding_service
from ..services.vector_store import vector_store
from ..services.retriever import rag_retriever
from ..services.ingestion import process_document as ingest_process_document
from ..services.ingestion import rebuild_vectors as ingest_rebuild_vectors
from ..services.ingestion import build_graph as ingest_build_graph
from ..queue import enqueue_job
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Eval / Benchmarks APIs
from .eval_routes import router as eval_router

router.include_router(eval_router)


# ==================== Schemas ====================

class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    chunk_size: Optional[int] = 500
    chunk_overlap: Optional[int] = 50
    cleaning_rules: Optional[dict] = None


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    cleaning_rules: Optional[dict] = None


class PreviewChunksRequest(BaseModel):
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    cleaning_rules: Optional[dict] = None
    limit: int = 50


class URLImportRequest(BaseModel):
    url: str
    knowledge_base_id: int


class ChatRequest(BaseModel):
    query: str
    knowledge_base_id: Optional[int] = None
    top_k: Optional[int] = 5


class ChatResponse(BaseModel):
    answer: str
    sources: List[dict]


# ==================== Knowledge Base APIs ====================

@router.get("/knowledge-bases")
def list_knowledge_bases(db: Session = Depends(get_mysql_db)):
    """获取知识库列表"""
    kbs = db.query(KnowledgeBase).filter(KnowledgeBase.is_active == True).all()
    return {"items": [kb.to_dict() for kb in kbs]}


@router.post("/knowledge-bases")
def create_knowledge_base(
    data: KnowledgeBaseCreate,
    db: Session = Depends(get_mysql_db),
):
    """创建知识库"""
    # 检查名称是否重复
    existing = db.query(KnowledgeBase).filter(KnowledgeBase.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Knowledge base '{data.name}' already exists")
    
    kb = KnowledgeBase(
        name=data.name,
        description=data.description,
        chunk_size=data.chunk_size,
        chunk_overlap=data.chunk_overlap,
    )
    if data.cleaning_rules is not None:
        kb.cleaning_rules = json.dumps(data.cleaning_rules, ensure_ascii=False)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    
    return kb.to_dict()


@router.get("/knowledge-bases/{kb_id}")
def get_knowledge_base(kb_id: int, db: Session = Depends(get_mysql_db)):
    """获取知识库详情"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb.to_dict()


@router.put("/knowledge-bases/{kb_id}")
def update_knowledge_base(
    kb_id: int,
    data: KnowledgeBaseUpdate,
    db: Session = Depends(get_mysql_db),
):
    """更新知识库"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    if data.name is not None:
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description
    if data.is_active is not None:
        kb.is_active = data.is_active
    if data.chunk_size is not None:
        kb.chunk_size = data.chunk_size
    if data.chunk_overlap is not None:
        kb.chunk_overlap = data.chunk_overlap
    if data.cleaning_rules is not None:
        kb.cleaning_rules = json.dumps(data.cleaning_rules, ensure_ascii=False)
    
    db.commit()
    db.refresh(kb)
    return kb.to_dict()


@router.delete("/knowledge-bases/{kb_id}")
def delete_knowledge_base(kb_id: int, db: Session = Depends(get_mysql_db)):
    """删除知识库（软删除）"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    kb.is_active = False
    db.commit()
    return {"message": "Knowledge base deleted"}


@router.get("/knowledge-bases/{kb_id}/stats")
def get_knowledge_base_stats(kb_id: int, db: Session = Depends(get_mysql_db)):
    """获取知识库统计信息"""
    from sqlalchemy import text
    from ..database import get_pgvector_session
    
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # 获取文档列表
    docs = db.query(Document).filter(
        Document.knowledge_base_id == kb_id
    ).all()
    
    doc_ids = [d.id for d in docs]
    
    # 统计向量信息
    parent_count = 0
    child_count = 0
    total_vectors = 0
    avg_chunk_size = 0
    
    if doc_ids:
        with get_pgvector_session() as pg_session:
            # 使用SQLAlchemy text查询
            result = pg_session.execute(text("""
                SELECT 
                    COUNT(*) FILTER (WHERE is_parent = TRUE) as parent_count,
                    COUNT(*) FILTER (WHERE is_parent = FALSE OR is_parent IS NULL) as child_count,
                    COUNT(*) as total,
                    AVG(LENGTH(content)) as avg_size
                FROM rag_vectors 
                WHERE document_id = ANY(:doc_ids)
            """), {"doc_ids": doc_ids})
            row = result.fetchone()
            if row:
                parent_count = row[0] or 0
                child_count = row[1] or 0
                total_vectors = row[2] or 0
                avg_chunk_size = int(row[3]) if row[3] else 0
    
    # 计算文档统计
    total_docs = len(docs)
    completed_docs = sum(1 for d in docs if d.status == "completed")
    failed_docs = sum(1 for d in docs if d.status == "failed")
    processing_docs = sum(1 for d in docs if d.status == "processing")
    
    # 计算分块分布
    chunk_distribution = {}
    for d in docs:
        count = d.chunk_count or 0
        if count == 0:
            bucket = "0"
        elif count <= 10:
            bucket = "1-10"
        elif count <= 50:
            bucket = "11-50"
        elif count <= 100:
            bucket = "51-100"
        else:
            bucket = "100+"
        chunk_distribution[bucket] = chunk_distribution.get(bucket, 0) + 1
    
    return {
        "knowledge_base": {
            "id": kb.id,
            "name": kb.name,
            "chunk_size": kb.chunk_size,
            "chunk_overlap": kb.chunk_overlap,
        },
        "documents": {
            "total": total_docs,
            "completed": completed_docs,
            "processing": processing_docs,
            "failed": failed_docs,
        },
        "vectors": {
            "total": total_vectors,
            "parents": parent_count,
            "children": child_count,
            "parent_child_ratio": f"1:{child_count // parent_count if parent_count > 0 else 0}",
            "avg_chunk_size": avg_chunk_size,
        },
        "chunk_distribution": chunk_distribution,
    }


# ==================== Helpers ====================

def update_kb_document_count(db: Session, kb_id: int):
    """更新知识库文档计数 (计算所有非软删除的文档)"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if kb:
        kb.document_count = db.query(Document).filter(
            Document.knowledge_base_id == kb.id
        ).count()
        db.commit()


async def _schedule_job(
    background_tasks: BackgroundTasks,
    queue_function: str,
    fallback,
    request_id: str | None,
    *args,
):
    """Schedule a job via ARQ when enabled, otherwise fallback to BackgroundTasks."""
    if settings.use_job_queue:
        try:
            return await enqueue_job(queue_function, *args, job_id=request_id)
        except Exception as e:
            logger.warning(f"Failed to enqueue job {queue_function}, falling back to BackgroundTasks: {e}")

    background_tasks.add_task(fallback, *args)
    return None


def _get_request_id_from_headers(req: Request) -> str | None:
    """Best-effort extract UUID request id for job/audit correlation."""
    raw = (req.headers.get("X-Request-Id") or "").strip()
    if not raw:
        return None
    try:
        import uuid

        return str(uuid.UUID(raw))
    except Exception:
        return None


# ==================== Document APIs ====================

@router.get("/knowledge-bases/{kb_id}/documents")
def list_documents(kb_id: int, db: Session = Depends(get_mysql_db)):
    """获取知识库的文档列表"""
    docs = db.query(Document).filter(Document.knowledge_base_id == kb_id).all()
    return {"items": [doc.to_dict() for doc in docs]}


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/reindex")
async def reindex_document(
    kb_id: int,
    doc_id: int,
    req: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_mysql_db),
):
    """重建单个文档的向量（仅该文档）。"""
    doc = db.query(Document).filter(Document.id == doc_id, Document.knowledge_base_id == kb_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc.status = "queued"
    doc.error_message = None
    db.commit()
    db.refresh(doc)

    request_id = _get_request_id_from_headers(req)
    job_id = await _schedule_job(background_tasks, "process_document_job", ingest_process_document, request_id, doc.id)

    payload = doc.to_dict()
    payload["job_id"] = job_id
    return payload


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/chunks")
def list_document_chunks(
    kb_id: int,
    doc_id: int,
    offset: int = 0,
    limit: int = 50,
    include_parents: bool = True,
    db: Session = Depends(get_mysql_db),
):
    """列出某文档的分块（来自 pgvector rag_vectors）。"""
    doc = db.query(Document).filter(Document.id == doc_id, Document.knowledge_base_id == kb_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    from sqlalchemy import text
    from ..database import get_pgvector_session

    where = "document_id = :doc_id"
    if not include_parents:
        where += " AND (is_parent = FALSE OR is_parent IS NULL)"

    # Parents first (outline), then children.
    sql = f"""
        SELECT id, chunk_index, content, metadata, parent_id, is_parent, created_at
        FROM rag_vectors
        WHERE {where}
        ORDER BY is_parent DESC, chunk_index ASC
        LIMIT :limit OFFSET :offset
    """

    with get_pgvector_session() as pg:
        rows = pg.execute(text(sql), {"doc_id": doc_id, "limit": limit, "offset": offset}).fetchall()

    items = []
    for r in rows:
        meta = r[3]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        content = r[2] or ""
        items.append(
            {
                "id": int(r[0]),
                "chunk_index": int(r[1]),
                "content": content,
                "metadata": meta or {},
                "parent_id": r[4],
                "is_parent": bool(r[5]) if r[5] is not None else False,
                "created_at": r[6].isoformat() if r[6] else None,
                "tokens_estimate": max(1, len(content) // 4),
            }
        )

    return {
        "document": doc.to_dict(),
        "offset": offset,
        "limit": limit,
        "items": items,
    }


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/outline")
def get_document_outline(
    kb_id: int,
    doc_id: int,
    db: Session = Depends(get_mysql_db),
):
    doc = db.query(Document).filter(Document.id == doc_id, Document.knowledge_base_id == kb_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    row = db.query(DocumentOutline).filter(DocumentOutline.document_id == doc_id).first()
    if not row:
        return {"document": doc.to_dict(), "items": []}

    payload = row.to_dict()
    return {"document": doc.to_dict(), "extraction": payload.get("extraction"), "items": payload.get("outline") or []}


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/preview-chunks")
async def preview_document_chunks(
    kb_id: int,
    doc_id: int,
    req: PreviewChunksRequest,
    db: Session = Depends(get_mysql_db),
):
    """预览某文档在指定规则/参数下的分块结果（dry-run，不写入向量表）。"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    doc = db.query(Document).filter(Document.id == doc_id, Document.knowledge_base_id == kb_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.file_type in ("image", "audio", "video"):
        raise HTTPException(status_code=400, detail=f"Preview is not supported for file_type={doc.file_type}")

    from ..services.minio_service import minio_service
    from ..services.ingestion import _ensure_loader_filename
    from ..services.text_cleaner import apply_cleaning_rules
    from ..services.chunker import DocumentChunker

    local_path = minio_service.download_file(doc.file_path) if doc.file_path else None
    if not local_path or not os.path.exists(local_path):
        raise HTTPException(status_code=500, detail="Failed to download document from storage")

    try:
        filename = _ensure_loader_filename(doc)
        loaded = document_loader.load(local_path, filename)

        # Resolve effective config (request overrides KB default)
        base_rules = None
        if kb.cleaning_rules:
            try:
                base_rules = json.loads(kb.cleaning_rules)
            except Exception:
                base_rules = None

        effective_rules = req.cleaning_rules if req.cleaning_rules is not None else base_rules
        chunk_size = int(req.chunk_size if req.chunk_size is not None else kb.chunk_size)
        chunk_overlap = int(req.chunk_overlap if req.chunk_overlap is not None else kb.chunk_overlap)

        cleaned = apply_cleaning_rules(loaded.content, effective_rules)

        # We already applied cleaning; do not preprocess again in chunker.
        chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap, preprocess=False)
        parents, children = chunker.semantic_hierarchical_chunk(
            content=cleaned,
            metadata=loaded.metadata,
            similarity_threshold=0.5,
            parent_max_size=chunk_size * 4,
            child_max_size=chunk_size,
        )

        # Build preview items (truncate content)
        limit = max(1, min(int(req.limit or 50), 200))
        preview = []
        for c in (parents + children)[:limit]:
            text = c.content or ""
            preview.append(
                {
                    "chunk_index": c.index,
                    "is_parent": bool(c.is_parent),
                    "parent_index": c.parent_index,
                    "content": text[:800],
                    "tokens_estimate": max(1, len(text) // 4),
                    "metadata": c.metadata,
                }
            )

        return {
            "document": doc.to_dict(),
            "knowledge_base": kb.to_dict(),
            "effective": {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "cleaning_rules": effective_rules,
            },
            "counts": {"parents": len(parents), "children": len(children)},
            "items": preview,
        }
    finally:
        try:
            if local_path and os.path.exists(local_path):
                os.remove(local_path)
        except Exception:
            pass


@router.post("/knowledge-bases/{kb_id}/documents/upload")
async def upload_document(
    kb_id: int,
    req: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_mysql_db),
):
    """上传文档"""
    # 检查知识库
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # 检查文件类型
    if not document_loader.is_supported(file.filename):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.filename}")
    
    # 检查文件大小
    content = await file.read()
    if len(content) > settings.max_file_size:
        raise HTTPException(status_code=400, detail="File too large")
    
    # 上传到 MinIO
    from ..services.minio_service import minio_service
    import uuid
    
    # 生成唯一对象名：kb_{id}/{uuid}_{filename}
    object_name = f"kb_{kb_id}/{uuid.uuid4().hex}_{file.filename}"
    
    # 根据文件类型设置 content-type
    content_type_map = {
        "pdf": "application/pdf",
        "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "markdown": "text/markdown",
        "text": "text/plain",
    }
    file_type = document_loader.get_file_type(file.filename)
    content_type = content_type_map.get(file_type, "application/octet-stream")
    
    # 上传到 MinIO
    minio_path = minio_service.upload_file(content, object_name, content_type)
    if not minio_path:
        raise HTTPException(status_code=500, detail="Failed to upload file to storage")
    
    # 创建文档记录
    doc = Document(
        knowledge_base_id=kb_id,
        filename=file.filename,
        file_type=file_type,
        file_size=len(content),
        file_path=object_name,  # 保存 MinIO 对象名
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    # 更新知识库文档计数
    update_kb_document_count(db, kb_id)
    
    # 入队/后台处理：从 MinIO 下载后处理
    doc.status = "queued"
    db.commit()
    request_id = _get_request_id_from_headers(req)
    job_id = await _schedule_job(background_tasks, "process_document_job", ingest_process_document, request_id, doc.id)

    payload = doc.to_dict()
    payload["job_id"] = job_id
    return payload


@router.post("/knowledge-bases/{kb_id}/documents/import-url")
async def import_url(
    kb_id: int,
    data: URLImportRequest,
    req: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_mysql_db),
):
    """从URL导入网页内容"""
    # 检查知识库
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # 抓取网页
    try:
        page = await web_crawler.crawl(data.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to crawl URL: {e}")
    
    # 上传到 MinIO
    from ..services.minio_service import minio_service
    import uuid
    
    # 将网页内容作为文本文件存储
    content_bytes = page.content.encode('utf-8')
    safe_title = (page.title or "webpage")[:50].replace("/", "_").replace("\\", "_")
    object_name = f"kb_{kb_id}/{uuid.uuid4().hex}_{safe_title}.txt"
    
    minio_path = minio_service.upload_file(content_bytes, object_name, "text/plain; charset=utf-8")
    
    # 创建文档记录
    doc = Document(
        knowledge_base_id=kb_id,
        filename=page.title or data.url,
        file_type="webpage",
        file_size=len(content_bytes),
        file_path=object_name if minio_path else None,  # 保存 MinIO 路径
        source_url=data.url,
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    # 更新知识库文档计数
    update_kb_document_count(db, kb_id)
    
    doc.status = "queued"
    db.commit()
    request_id = _get_request_id_from_headers(req)
    job_id = await _schedule_job(background_tasks, "process_document_job", ingest_process_document, request_id, doc.id)

    payload = doc.to_dict()
    payload["job_id"] = job_id
    return payload


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_mysql_db)):
    """删除文档"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # 删除向量
    vector_store.delete_document_vectors(doc_id)
    
    # 删除文档记录
    kb_id = doc.knowledge_base_id
    db.delete(doc)
    db.commit()
    
    # 更新知识库文档计数
    update_kb_document_count(db, kb_id)
    
    return {"message": "Document deleted"}


@router.get("/documents/{doc_id}/chunks")
def get_document_chunks(doc_id: int, db: Session = Depends(get_mysql_db)):
    """获取文档的所有分块"""
    # 检查文档是否存在
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # 从pgvector获取分块
    from sqlalchemy import text
    from ..database import get_pgvector_session
    
    with get_pgvector_session() as pg_session:
        result = pg_session.execute(
            text(f"""
                SELECT chunk_index, content, metadata
                FROM rag_vectors
                WHERE document_id = {doc_id}
                ORDER BY chunk_index
            """)
        )
        
        chunks = []
        for row in result:
            chunks.append({
                "index": row.chunk_index,
                "content": row.content,
                "metadata": row.metadata if isinstance(row.metadata, dict) else {},
                "char_count": len(row.content),
            })
    

    return {
        "document_id": doc_id,
        "filename": doc.filename,
        "total_chunks": len(chunks),
        "chunks": chunks,
    }


@router.get("/documents/{doc_id}/images")
def get_document_images(doc_id: int, db: Session = Depends(get_mysql_db)):
    """获取文档关联的图片列表"""
    from ..models import DocumentImage
    
    # 检查文档是否存在
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    images = db.query(DocumentImage).filter(
        DocumentImage.document_id == doc_id
    ).order_by(DocumentImage.image_index).all()
    
    return {
        "items": [img.to_dict() for img in images]
    }


@router.post("/analyze-chart")
async def analyze_chart_endpoint(
    file: UploadFile = File(...)
):
    """
    独立图表分析接口 (Chart QA)
    直接上传图片，返回 JSON 数据和分析结论
    """
    from ..services.vlm_service import vlm_service
    
    # 验证图片格式
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    content = await file.read()
    
    try:
        # 调用 VLM 进行图表分析
        response = await vlm_service.analyze_chart(content)
        
        # 尝试解析 JSON 部分 (如果 VLM 返回了 Markdown 代码块)
        import re
        import json
        
        raw_content = response.content
        json_data = None
        
        # 提取 ```json ... ``` 内容
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw_content, re.DOTALL)
        if json_match:
            try:
                json_str = json_match.group(1)
                json_data = json.loads(json_str)
            except:
                pass
        
        return {
            "raw_response": raw_content,
            "json_data": json_data
        }
    except Exception as e:
        logger.error(f"Chart analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Chat API ====================

class StreamChatRequest(BaseModel):
    query: str
    knowledge_base_id: Optional[int] = None
    top_k: Optional[int] = 5
    session_id: Optional[str] = None  # 用于对话历史
    history: Optional[List[dict]] = None  # 前端传递的历史对话 [{"role": "user|assistant", "content": "..."}]


@router.post("/chat", response_model=ChatResponse)
async def chat(data: ChatRequest):
    """RAG问答"""
    response = await rag_retriever.answer(
        query=data.query,
        knowledge_base_id=data.knowledge_base_id,
        top_k=data.top_k,
    )
    return ChatResponse(
        answer=response.answer,
        sources=response.sources,
    )


@router.post("/chat/stream")
async def chat_stream(data: StreamChatRequest):
    """
    流式RAG问答 (Server-Sent Events)
    
    返回格式:
    - data: {"type": "source", "sources": [...]}  # 首先返回检索源
    - data: {"type": "token", "content": "..."}   # 逐token返回
    - data: {"type": "done"}                      # 完成标记
    """
    from fastapi.responses import StreamingResponse
    from ..services.llm_service import llm_service
    import json
    
    async def generate():
        try:
            # 获取对话历史（优先使用前端传递的历史）
            from ..services.conversation_memory import conversation_memory
            history_text = ""
            if data.history:
                # 使用前端传递的历史
                lines = []
                for msg in data.history:
                    role_cn = "用户" if msg.get("role") == "user" else "助手"
                    lines.append(f"{role_cn}: {msg.get('content', '')}")
                history_text = "\n".join(lines)
            elif data.session_id:
                # 回退到内存中的会话历史
                history_text = conversation_memory.get_history_text(data.session_id)
            
            # 判断是否使用知识库
            if data.knowledge_base_id:
                # ===== 有知识库：RAG 模式 =====
                # 1. 检索相关文档
                results = await rag_retriever.retrieve(
                    query=data.query,
                    knowledge_base_id=data.knowledge_base_id,
                    top_k=data.top_k,
                )
                
                # 2. 发送检索源信息
                sources = []
                for i, r in enumerate(results):
                    # 获取文档名
                    doc_name = "Unknown"
                    try:
                        from ..database import MySQLSessionLocal
                        from ..models import Document
                        db = MySQLSessionLocal()
                        doc = db.query(Document).filter(Document.id == r.document_id).first()
                        if doc:
                            doc_name = doc.filename
                        db.close()
                    except:
                        pass
                    
                    sources.append({
                        "index": i + 1,
                        "document_name": doc_name,
                        "document_id": r.document_id,
                        "chunk_index": r.chunk_index,
                        "content_preview": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                        "score": r.score,
                    })
                
                yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"
                
                # 3. 构建上下文
                context = "\n\n".join([
                    f"[{i+1}] {r.content}" 
                    for i, r in enumerate(results)
                ])
                
                # 4. 构建 RAG 提示
                system_prompt = """你是一个专业的知识库问答助手。请根据提供的参考资料回答用户问题。

规则：
1. 仅基于参考资料回答，如果资料不足以回答，请说明
2. 引用时使用 [1], [2] 等标记指向对应的参考资料
3. 回答要准确、专业、有条理
4. 如果有对话历史，请注意保持上下文连贯性

参考资料：
{context}"""

                if history_text:
                    system_prompt += f"\n\n对话历史：\n{history_text}"
                
                full_answer = ""

                messages = [
                    {"role": "system", "content": system_prompt.format(context=context)},
                    {"role": "user", "content": data.query},
                ]

                async for content in llm_service.stream_messages(
                    messages,
                    model=settings.llm_model,
                    temperature=0.7,
                    timeout_sec=settings.llm_timeout_sec,
                ):
                    full_answer += content
                    yield f"data: {json.dumps({'type': 'token', 'content': content}, ensure_ascii=False)}\n\n"
            else:
                # ===== 无知识库：纯 LLM 对话模式 =====
                yield f"data: {json.dumps({'type': 'sources', 'sources': []}, ensure_ascii=False)}\n\n"
                
                system_prompt = """你是一个智能助手，可以回答各种问题。请根据用户的问题提供准确、有帮助的回答。

如果有对话历史，请注意保持上下文连贯性。"""

                if history_text:
                    system_prompt += f"\n\n对话历史：\n{history_text}"
                
                full_answer = ""

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": data.query},
                ]

                async for content in llm_service.stream_messages(
                    messages,
                    model=settings.llm_model,
                    temperature=0.7,
                    timeout_sec=settings.llm_timeout_sec,
                ):
                    full_answer += content
                    yield f"data: {json.dumps({'type': 'token', 'content': content}, ensure_ascii=False)}\n\n"
            
            # 保存对话历史
            if data.session_id:
                conversation_memory.add_message(data.session_id, "user", data.query)
                conversation_memory.add_message(data.session_id, "assistant", full_answer)
            
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )



# ==================== Retrieve API (for external agents) ====================

class RetrieveRequest(BaseModel):
    query: str
    knowledge_base_id: Optional[int] = None
    top_k: Optional[int] = 5


class RetrieveResult(BaseModel):
    content: str
    score: float
    document_id: int
    chunk_index: int
    metadata: dict


class RetrieveResponse(BaseModel):
    query: str
    results: List[RetrieveResult]
    total: int


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(data: RetrieveRequest):
    """
    纯检索API - 仅返回相关文档片段，不调用LLM
    
    适用于外部Agent集成，Agent可以使用自己的LLM处理检索结果
    """
    # 获取检索结果（同步调用 -> 异步调用）
    results = await rag_retriever.retrieve(
        query=data.query,
        knowledge_base_id=data.knowledge_base_id,
        top_k=data.top_k,
    )
    
    return RetrieveResponse(
        query=data.query,
        results=[
            RetrieveResult(
                content=r.content,
                score=r.score,
                document_id=r.document_id,
                chunk_index=r.chunk_index,
                metadata=r.metadata,
            )
            for r in results
        ],
        total=len(results),
    )


# ==================== GraphRAG API ====================

from ..services.graph_builder import graph_builder
from ..services.graph_retriever import graph_retriever
from langchain_core.documents import Document as LangChainDocument

@router.post("/knowledge-bases/{kb_id}/build-graph")
async def build_knowledge_graph(
    kb_id: int,
    req: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_mysql_db),
):
    """
    触发构建知识图谱任务
    """
    request_id = _get_request_id_from_headers(req)
    job_id = await _schedule_job(background_tasks, "build_graph_job", ingest_build_graph, request_id, kb_id)
    return {"message": "Graph build queued" if job_id else "Graph build started", "kb_id": kb_id, "job_id": job_id}

async def _run_graph_build_task(kb_id: int):
    """后台运行图构建 - 从 MinIO 下载原始文档构建"""
    try:
        from ..database import get_mysql_session
        from ..services.graph_builder import graph_builder
        from ..services.document_loader import document_loader
        from ..services.minio_service import minio_service
        from langchain_core.documents import Document as LangChainDocument
        
        logger.info(f"Starting graph build for KB {kb_id} (from MinIO)")
        
        # 获取需要处理的文档列表
        doc_infos = []
        with get_mysql_session() as mysql_db:
            docs = mysql_db.query(Document).filter(
                Document.knowledge_base_id == kb_id,
                Document.graph_built == False
            ).all()
            
            if not docs:
                logger.info(f"No new documents to build graph for KB {kb_id}")
                return
            
            # 将文档信息复制出来，避免Session关闭后无法访问
            for doc in docs:
                doc_infos.append({
                    "id": doc.id,
                    "filename": doc.filename,
                    "file_path": doc.file_path
                })

        logger.info(f"Found {len(doc_infos)} new documents to build graph for KB {kb_id}")
        
        # 逐个处理文档
        for doc_info in doc_infos:
            doc_id = doc_info["id"]
            filename = doc_info["filename"]
            file_path = doc_info["file_path"]
            temp_file = None
            
            try:
                if not file_path:
                    logger.warning(f"No file_path for doc {doc_id}")
                    continue
                
                # 1. 下载和加载
                temp_file = minio_service.download_file(file_path)
                if not temp_file:
                    logger.warning(f"Failed to download from MinIO: {file_path}")
                    continue
                
                # 处理文件名
                filename_for_loader = filename
                if not os.path.splitext(filename)[1]:
                    ext = os.path.splitext(file_path)[1]
                    if ext: filename_for_loader += ext
                
                loaded = document_loader.load(temp_file, filename_for_loader)
                content = loaded.content
                
                # 2. 分块
                doc_chunks = []
                chunk_size = 3000
                for i in range(0, len(content), chunk_size):
                    chunk = content[i:i+chunk_size]
                    if len(chunk.strip()) > 100:
                        doc_chunks.append(
                            LangChainDocument(
                                page_content=chunk,
                                metadata={"source": filename, "doc_id": doc_id, "chunk": i // chunk_size}
                            )
                        )
                
                # 3. 构建图谱
                if doc_chunks:
                    logger.info(f"Building graph for {filename} ({len(doc_chunks)} chunks)")
                    await graph_builder.build_from_documents(doc_chunks)
                    
                    # 4. 立即更新状态
                    with get_mysql_session() as update_db:
                        d = update_db.query(Document).filter(Document.id == doc_id).first()
                        if d:
                            d.graph_built = True
                            update_db.commit()
                            logger.info(f"Successfully built graph for doc {doc_id} ({filename})")
                else:
                    logger.warning(f"No valid chunks for doc {doc_id}")
                    
            except Exception as e:
                logger.error(f"Error processing doc {doc_id} ({filename}): {e}")
            finally:
                if temp_file and os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
                
    except Exception as e:
        logger.error(f"Error in graph build task: {e}")
        import traceback
        logger.error(traceback.format_exc())


# ==================== Rebuild Vectors API ====================

@router.post("/knowledge-bases/{kb_id}/rebuild-vectors")
async def rebuild_vectors(
    kb_id: int,
    req: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_mysql_db),
):
    """
    批量重建知识库向量 (使用新的父子索引策略)
    
    删除现有向量并重新处理所有文档
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    doc_count = db.query(Document).filter(Document.knowledge_base_id == kb_id).count()
    
    request_id = _get_request_id_from_headers(req)
    job_id = await _schedule_job(background_tasks, "rebuild_vectors_job", ingest_rebuild_vectors, request_id, kb_id)

    return {
        "message": "Rebuild vectors queued" if job_id else "Rebuild vectors started",
        "kb_id": kb_id,
        "job_id": job_id,
        "document_count": doc_count
    }

async def _run_rebuild_vectors_task(kb_id: int):
    """后台运行向量重建任务"""
    try:
        from ..database import get_mysql_session
        from ..services.document_loader import document_loader
        from ..services.minio_service import minio_service
        from ..services.chunker import DocumentChunker
        
        logger.info(f"Starting rebuild vectors for KB {kb_id}")
        
        # 获取所有文档
        doc_infos = []
        with get_mysql_session() as mysql_db:
            kb = mysql_db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
            kb_chunk_size = kb.chunk_size if kb else 500
            kb_chunk_overlap = kb.chunk_overlap if kb else 50
            
            docs = mysql_db.query(Document).filter(
                Document.knowledge_base_id == kb_id
            ).all()
            
            for doc in docs:
                doc_infos.append({
                    "id": doc.id,
                    "filename": doc.filename,
                    "file_path": doc.file_path
                })
        
        logger.info(f"Found {len(doc_infos)} documents to rebuild in KB {kb_id}")
        
        chunker = DocumentChunker()
        
        for doc_info in doc_infos:
            doc_id = doc_info["id"]
            filename = doc_info["filename"]
            file_path = doc_info["file_path"]
            temp_file = None
            
            try:
                logger.info(f"Rebuilding vectors for doc {doc_id} ({filename})")
                
                # 1. 删除旧向量
                deleted = vector_store.delete_document_vectors(doc_id)
                logger.info(f"Deleted {deleted} old vectors for doc {doc_id}")
                
                # 2. 下载原始文件
                if not file_path:
                    logger.warning(f"No file_path for doc {doc_id}, skipping")
                    continue
                    
                temp_file = minio_service.download_file(file_path)
                if not temp_file:
                    logger.warning(f"Failed to download from MinIO: {file_path}")
                    continue
                
                # 3. 重新加载文档
                filename_for_loader = filename
                if not os.path.splitext(filename)[1]:
                    ext = os.path.splitext(file_path)[1]
                    if ext: filename_for_loader += ext
                    
                loaded = document_loader.load(temp_file, filename_for_loader)
                
                # 4. 语义父子分块
                parent_chunks, child_chunks = chunker.semantic_hierarchical_chunk(
                    content=loaded.content,
                    metadata=loaded.metadata,
                    similarity_threshold=0.5,
                    parent_max_size=kb_chunk_size * 4,
                    child_max_size=kb_chunk_size,
                )
                
                # 5. 向量化
                if parent_chunks or child_chunks:
                    parent_texts = [p.content for p in parent_chunks]
                    parent_embeddings = embedding_service.embed_texts(parent_texts) if parent_texts else []
                    
                    child_texts = [c.content for c in child_chunks]
                    child_embeddings = embedding_service.embed_texts(child_texts) if child_texts else []
                    
                    parent_data = [
                        (p.index, p.content, emb, p.metadata)
                        for p, emb in zip(parent_chunks, parent_embeddings)
                    ]
                    
                    child_data = [
                        (c.index, c.content, emb, c.metadata, c.parent_index)
                        for c, emb in zip(child_chunks, child_embeddings)
                    ]
                    
                    # 6. 存储新向量
                    vector_store.store_hierarchical_vectors(doc_id, parent_data, child_data)
                    
                    # 7. 更新文档状态
                    total_chunks = len(parent_chunks) + len(child_chunks)
                    with get_mysql_session() as update_db:
                        d = update_db.query(Document).filter(Document.id == doc_id).first()
                        if d:
                            d.chunk_count = total_chunks
                            d.status = "completed"
                            update_db.commit()
                    
                    logger.info(f"Rebuilt doc {doc_id}: {len(parent_chunks)} parents + {len(child_chunks)} children")
                    
            except Exception as e:
                logger.error(f"Error rebuilding doc {doc_id} ({filename}): {e}")
                import traceback
                logger.error(traceback.format_exc())
            finally:
                if temp_file and os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
        
        logger.info(f"Rebuild vectors completed for KB {kb_id}")
        
    except Exception as e:
        logger.error(f"Error in rebuild vectors task: {e}")
        import traceback
        logger.error(traceback.format_exc())

@router.post("/graph/retrieve", response_model=RetrieveResponse)
async def graph_retrieve(data: RetrieveRequest):
    """
    混合检索/图检索API
    """
    results = await graph_retriever.retrieve(
        query=data.query,
        knowledge_base_id=data.knowledge_base_id,
        depth=2
    )
    
    # 转换为 RetrieveResult 格式
    formatted_results = []
    for r in results:
        formatted_results.append(RetrieveResult(
            content=r["content"],
            score=r["score"],
            document_id=0, # 图检索可能不对应单一文档ID
            chunk_index=0,
            metadata=r["metadata"]
        ))
        
    return RetrieveResponse(
        query=data.query,
        results=formatted_results,
        total=len(formatted_results)
    )


# ==================== Evaluation API ====================

class EvaluationRequest(BaseModel):
    question: str
    answer: str
    contexts: Optional[List[str]] = []

class EvaluationResponse(BaseModel):
    faithfulness: Optional[float] = None
    reasoning_faithfulness: Optional[str] = None
    answer_relevance: Optional[float] = None
    reasoning_relevance: Optional[str] = None

@router.post("/evaluate", response_model=EvaluationResponse)
async def evaluate_rag(data: EvaluationRequest):
    """
    RAG 效果评估 (LLM-as-a-Judge)
    
    同时评估:
    1. Faithfulness (需要 contexts)
    2. Answer Relevance
    """
    from ..services.evaluator import rag_evaluator
    
    response = EvaluationResponse()
    
    # 1. 评估信实度 (如果提供了上下文)
    if data.contexts:
        faith_result = await rag_evaluator.evaluate_faithfulness(
            question=data.question,
            answer=data.answer,
            contexts=data.contexts
        )
        response.faithfulness = faith_result.score
        response.reasoning_faithfulness = faith_result.reasoning
        
    # 2. 评估相关性
    rel_result = await rag_evaluator.evaluate_answer_relevance(
        question=data.question,
        answer=data.answer
    )
    response.answer_relevance = rel_result.score
    response.reasoning_relevance = rel_result.reasoning
    
    return response


# ==================== Multimodal APIs ====================

class MultiModalQueryRequest(BaseModel):
    query: str
    knowledge_base_id: Optional[int] = None
    top_k: Optional[int] = 5


class MultiModalQueryResponse(BaseModel):
    answer: str
    sources: List[dict]
    images: List[dict]
    has_multimodal_context: bool


class ReportRequest(BaseModel):
    topic: str
    format: Optional[str] = "markdown"  # markdown | html
    include_charts: Optional[bool] = True
    max_sections: Optional[int] = 5


class ReportResponse(BaseModel):
    title: str
    content: str
    format: str
    word_count: int
    generated_at: str



@router.post("/upload-image")
async def upload_image_generic(
    file: UploadFile = File(...)
):
    """
    通用图片上传接口 (用于对话会话)
    
    1. 上传到 MinIO
    2. VLM 生成描述
    3. 返回 URL 和描述
    """
    from ..services.minio_service import minio_service
    from ..services.vlm_service import vlm_service
    import uuid
    
    # 验证图片格式
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    content = await file.read()
    
    try:
        # 上传到 MinIO
        object_name = f"chat/images/{uuid.uuid4().hex}_{file.filename}"
        minio_path = minio_service.upload_file(content, object_name, file.content_type or "image/jpeg")
        
        # 获取访问 URL
        url = minio_service.get_presigned_url(object_name)
        
        # VLM 生成描述
        response = await vlm_service.analyze_image(content, "简单的描述这张图片")
        description = response.content
        
        return {
            "filename": file.filename,
            "url": url,
            "minio_path": object_name,
            "description": description
        }
    except Exception as e:
        logger.error(f"Image upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Note: Generic /upload-file endpoint moved to end of file (line ~2086)
# to support all file types including video/audio without validation

@router.post("/knowledge-bases/{kb_id}/upload-image")
async def upload_image(
    kb_id: int,
    req: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_mysql_db),
):
    """
    上传图片到知识库
    
    处理流程:
    1. VLM 生成图片描述
    2. 向量化描述文本
    3. 存入向量库
    """
    from ..services.image_encoder import image_encoder
    from ..services.vlm_service import vlm_service
    from ..services.minio_service import minio_service
    from ..models import DocumentImage
    import uuid
    
    # 检查知识库
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # 检查文件类型
    if not image_encoder.is_supported(file.filename):
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {file.filename}")
    
    # 读取文件内容
    content = await file.read()
    if len(content) > settings.max_image_size:
        raise HTTPException(status_code=400, detail="Image too large")
    
    # 上传到 MinIO
    object_name = f"kb_{kb_id}/images/{uuid.uuid4().hex}_{file.filename}"
    minio_path = minio_service.upload_file(content, object_name, file.content_type or "image/jpeg")
    
    # 创建文档记录（用于关联）
    doc = Document(
        knowledge_base_id=kb_id,
        filename=file.filename,
        file_type="image",
        file_size=len(content),
        file_path=object_name,
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    doc.status = "queued"
    db.commit()
    request_id = _get_request_id_from_headers(req)
    job_id = await _schedule_job(background_tasks, "process_document_job", ingest_process_document, request_id, doc.id)

    return {
        "document_id": doc.id,
        "filename": file.filename,
        "status": doc.status,
        "job_id": job_id,
        "message": "Image upload queued"
    }


@router.post("/knowledge-bases/{kb_id}/upload-audio")
async def upload_audio(
    kb_id: int,
    req: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_mysql_db),
):
    """
    上传音频到知识库
    
    处理流程:
    1. Whisper 语音转写
    2. 分块并向量化
    3. 存入向量库
    """
    from ..services.speech_service import speech_service
    from ..services.minio_service import minio_service
    import uuid
    
    # 检查知识库
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # 检查文件类型
    if not speech_service.is_supported(file.filename):
        raise HTTPException(status_code=400, detail=f"Unsupported audio type: {file.filename}")
    
    # 读取文件内容
    content = await file.read()
    
    # 上传到 MinIO
    object_name = f"kb_{kb_id}/audio/{uuid.uuid4().hex}_{file.filename}"
    minio_path = minio_service.upload_file(content, object_name, file.content_type or "audio/mpeg")
    
    # 创建文档记录
    doc = Document(
        knowledge_base_id=kb_id,
        filename=file.filename,
        file_type="audio",
        file_size=len(content),
        file_path=object_name,
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    doc.status = "queued"
    db.commit()
    request_id = _get_request_id_from_headers(req)
    job_id = await _schedule_job(background_tasks, "process_document_job", ingest_process_document, request_id, doc.id)

    return {
        "document_id": doc.id,
        "filename": file.filename,
        "status": doc.status,
        "job_id": job_id,
        "message": "Audio upload queued"
    }


@router.post("/knowledge-bases/{kb_id}/upload-video")
async def upload_video(
    kb_id: int,
    req: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_mysql_db),
):
    """
    上传视频到知识库
    
    处理流程:
    1. 抽取关键帧 + VLM 分析
    2. 提取音轨 + Whisper 转写
    3. 合并分析结果并向量化
    """
    from ..services.video_service import video_service
    from ..services.minio_service import minio_service
    import uuid
    
    # 检查知识库
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # 检查文件类型
    if not video_service.is_supported(file.filename):
        raise HTTPException(status_code=400, detail=f"Unsupported video type: {file.filename}")
    
    # 读取文件内容
    content = await file.read()
    
    # 上传到 MinIO
    object_name = f"kb_{kb_id}/video/{uuid.uuid4().hex}_{file.filename}"
    minio_path = minio_service.upload_file(content, object_name, file.content_type or "video/mp4")
    
    # 创建文档记录
    doc = Document(
        knowledge_base_id=kb_id,
        filename=file.filename,
        file_type="video",
        file_size=len(content),
        file_path=object_name,
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    doc.status = "queued"
    db.commit()
    request_id = _get_request_id_from_headers(req)
    job_id = await _schedule_job(background_tasks, "process_document_job", ingest_process_document, request_id, doc.id)

    return {
        "document_id": doc.id,
        "filename": file.filename,
        "status": doc.status,
        "job_id": job_id,
        "message": "Video upload queued"
    }


@router.post("/multimodal-query", response_model=MultiModalQueryResponse)
async def multimodal_query_generic(
    request: dict
):
    """
    通用多模态问答 (对话模式)
    
    接收前端传来的 text_query 和 image_description
    直接调用 VLM 进行问答
    """
    from ..services.vlm_service import vlm_service
    from ..services.llm_service import llm_service
    
    text_query = request.get("text_query", "")
    image_desc = request.get("image_description", "")
    
    # 构造组合 prompt
    prompt = f"用户问题: {text_query}\n\n图片内容描述:\n{image_desc}\n\n请结合图片内容回答用户问题。"
    
    answer = await llm_service.generate(
        prompt,
        model=settings.llm_model,
        timeout_sec=settings.llm_timeout_sec,
        temperature=0.7,
        system_prompt="你是一个多模态助手。请根据提供的图片描述和用户问题进行回答。",
    )
    
    return MultiModalQueryResponse(
        answer=answer,
        sources=[],
        images=[],
        has_multimodal_context=True
    )


@router.post("/multimodal-query/stream")
async def multimodal_query_stream(
    request: dict
):
    """
    流式多模态问答 (SSE)
    
    接收前端传来的 text_query 和 image_description
    以 Server-Sent Events 格式流式返回响应
    """
    from fastapi.responses import StreamingResponse
    from ..services.llm_service import llm_service
    
    text_query = request.get("text_query", "")
    image_desc = request.get("image_description", "")
    
    # 构造组合 prompt
    prompt = f"用户问题: {text_query}\n\n图片内容描述:\n{image_desc}\n\n请结合图片内容回答用户问题。"
    
    async def generate():
        messages = [
            {"role": "system", "content": "你是一个多模态助手。请根据提供的图片描述和用户问题进行回答。"},
            {"role": "user", "content": prompt},
        ]
        async for content in llm_service.stream_messages(
            messages,
            model=settings.llm_model,
            temperature=0.7,
            timeout_sec=settings.llm_timeout_sec,
        ):
            yield f"data: {content}\n\n"

        yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/vlm-stream")
async def vlm_stream(
    query: str = Form("描述这些图片的内容"),
    history: str = Form(default="[]"),
    files: List[UploadFile] = File(...)
):
    """
    直接 VLM 流式分析图片 + 问题
    
    接收图片文件、问题和历史对话，使用 VLM 直接分析并流式返回
    """
    from fastapi.responses import StreamingResponse
    from ..services.vlm_service import vlm_service
    import json as _json
    
    # 解析历史对话
    try:
        history_list = _json.loads(history) if history else []
    except _json.JSONDecodeError:
        history_list = []
    
    # 读取所有图片数据
    image_data_list = []
    for f in files:
        data = await f.read()
        image_data_list.append(data)
    
    logger.info(f"VLM stream: received {len(image_data_list)} images, {len(history_list)} history msgs, query: {query[:50]}...")
    
    async def generate():
        try:
            async for chunk in vlm_service.analyze_images_stream(image_data_list, query, history_list):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"VLM stream error: {e}")
            yield f"data: [ERROR] {str(e)}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/vlm-rag-stream")
async def vlm_rag_stream(
    query: str = Form("描述这些图片的内容"),
    knowledge_base_id: int = Form(...),
    history: str = Form(default="[]"),
    files: List[UploadFile] = File(...)
):
    """
    VLM + RAG 联合流式查询
    
    流程:
    1. VLM 分析图片，生成图片描述
    2. RAG 检索知识库相关内容
    3. LLM 结合图片描述+知识库+用户问题生成回答
    """
    from fastapi.responses import StreamingResponse
    from ..services.vlm_service import vlm_service
    from ..services.llm_service import llm_service
    import json as _json
    
    # 解析历史对话
    try:
        history_list = _json.loads(history) if history else []
    except _json.JSONDecodeError:
        history_list = []
    
    # 读取所有图片数据
    image_data_list = []
    for f in files:
        data = await f.read()
        image_data_list.append(data)
    
    logger.info(f"VLM-RAG stream: received {len(image_data_list)} images, kb_id={knowledge_base_id}, query: {query[:50]}...")
    
    async def generate():
        try:
            # 1. VLM 分析图片
            yield f"data: {json.dumps({'type': 'status', 'message': '正在分析图片...'}, ensure_ascii=False)}\n\n"
            
            image_description = ""
            async for chunk in vlm_service.analyze_images_stream(image_data_list, "请详细描述这些图片中的内容，包括文字、图表、数据等关键信息。"):
                image_description += chunk
            
            logger.info(f"VLM analysis complete, description length: {len(image_description)}")
            
            # 2. RAG 检索知识库
            yield f"data: {json.dumps({'type': 'status', 'message': '正在检索知识库...'}, ensure_ascii=False)}\n\n"
            
            # 构建增强查询：用户问题 + 图片关键词
            enhanced_query = f"{query}\n\n图片相关内容：{image_description[:500]}"
            
            results = await rag_retriever.retrieve(
                query=enhanced_query,
                knowledge_base_id=knowledge_base_id,
                top_k=5,
            )
            
            # 发送检索源信息
            sources = []
            for i, r in enumerate(results):
                doc_name = "Unknown"
                try:
                    from ..database import MySQLSessionLocal
                    from ..models import Document
                    db = MySQLSessionLocal()
                    doc = db.query(Document).filter(Document.id == r.document_id).first()
                    if doc:
                        doc_name = doc.filename
                    db.close()
                except:
                    pass
                
                sources.append({
                    "index": i + 1,
                    "document_name": doc_name,
                    "document_id": r.document_id,
                    "chunk_index": r.chunk_index,
                    "content_preview": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                    "score": r.score,
                })
            
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"
            
            # 3. 构建上下文
            context = "\n\n".join([
                f"[{i+1}] {r.content}" 
                for i, r in enumerate(results)
            ])
            
            # 4. LLM 生成回答 (vLLM)
            # 构建历史对话
            history_text = ""
            if history_list:
                lines = []
                for msg in history_list:
                    role_cn = "用户" if msg.get("role") == "user" else "助手"
                    lines.append(f"{role_cn}: {msg.get('content', '')}")
                history_text = "\n".join(lines)
            
            system_prompt = """你是一个专业的多模态知识库问答助手。请根据提供的图片分析结果和知识库参考资料回答用户问题。

规则：
1. 结合图片内容和知识库资料进行综合回答
2. 引用知识库时使用 [1], [2] 等标记
3. 如果知识库资料不足，可以基于图片内容直接回答
4. 回答要准确、专业、有条理

图片分析结果：
{image_description}

知识库参考资料：
{context}"""

            if history_text:
                system_prompt += f"\n\n对话历史：\n{history_text}"
            
            messages = [
                {
                    "role": "system",
                    "content": system_prompt.format(image_description=image_description, context=context),
                },
                {"role": "user", "content": query},
            ]

            async for content in llm_service.stream_messages(
                messages,
                model=settings.llm_model,
                temperature=0.7,
                timeout_sec=settings.llm_timeout_sec,
            ):
                yield f"data: {json.dumps({'type': 'token', 'content': content}, ensure_ascii=False)}\n\n"
            
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            logger.error(f"VLM-RAG stream error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/knowledge-bases/{kb_id}/multimodal-query", response_model=MultiModalQueryResponse)
async def multimodal_query(
    kb_id: int,
    query: str = Form(...),
    images: List[UploadFile] = File(default=None),
):
    """
    多模态问答
    
    支持:
    - 纯文本问题
    - 图文混合问题 (上传参考图片)
    """
    from ..services.multimodal_retriever import multimodal_retriever
    
    # 读取上传的图片
    image_data = []
    if images:
        for img_file in images:
            content = await img_file.read()
            image_data.append(content)
    
    # 执行多模态问答
    response = await multimodal_retriever.answer(
        query=query,
        images=image_data if image_data else None,
        knowledge_base_id=kb_id,
    )
    
    return MultiModalQueryResponse(
        answer=response.answer,
        sources=response.sources,
        images=response.images,
        has_multimodal_context=response.has_multimodal_context
    )


@router.post("/knowledge-bases/{kb_id}/generate-report", response_model=ReportResponse)
async def generate_report(
    kb_id: int,
    data: ReportRequest,
):
    """
    基于知识库生成报告
    
    自动:
    1. 拆分主题为多个子查询
    2. 多轮检索收集素材
    3. 生成结构化报告
    """
    from ..services.report_generator import report_generator
    
    report = await report_generator.generate(
        topic=data.topic,
        knowledge_base_id=kb_id,
        format=data.format,
        include_charts=data.include_charts,
        max_sections=data.max_sections,
    )
    
    return ReportResponse(
        title=report.title,
        content=report.content,
        format=report.format,
        word_count=report.word_count,
        generated_at=report.generated_at
    )


@router.post("/knowledge-bases/{kb_id}/voice-query")
async def voice_query(
    kb_id: int,
    audio: UploadFile = File(...),
):
    """
    语音问答
    
    1. Whisper 转写语音为文本
    2. 执行 RAG 问答
    3. 返回文字回答
    """
    from ..services.speech_service import speech_service
    
    # 转写语音
    content = await audio.read()
    transcription = await speech_service.transcribe(content)
    
    # 执行问答
    response = await rag_retriever.answer(
        query=transcription.text,
        knowledge_base_id=kb_id,
    )
    
    return {
        "transcribed_query": transcription.text,
        "language": transcription.language,
        "answer": response.answer,
        "sources": response.sources
    }


# ==================== Chat Session APIs ====================

class ChatSessionCreate(BaseModel):
    knowledge_base_id: Optional[int] = None
    title: Optional[str] = None


class ChatMessageCreate(BaseModel):
    role: str  # user / assistant
    content: Optional[str] = None
    image_paths: Optional[List[str]] = None


@router.get("/chat-sessions")
def list_chat_sessions(
    knowledge_base_id: Optional[int] = None,
    limit: int = 50,
    db: Session = Depends(get_mysql_db)
):
    """获取会话列表"""
    from ..models import ChatSession
    
    query = db.query(ChatSession).order_by(ChatSession.updated_at.desc())
    if knowledge_base_id:
        query = query.filter(ChatSession.knowledge_base_id == knowledge_base_id)
    
    sessions = query.limit(limit).all()
    return {"items": [s.to_dict() for s in sessions]}


@router.post("/chat-sessions")
def create_chat_session(
    data: ChatSessionCreate,
    db: Session = Depends(get_mysql_db)
):
    """创建新会话"""
    from ..models import ChatSession
    import uuid
    
    session = ChatSession(
        id=str(uuid.uuid4()),
        knowledge_base_id=data.knowledge_base_id,
        title=data.title or "新对话"
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    
    return session.to_dict()


@router.get("/chat-sessions/{session_id}")
def get_chat_session(session_id: str, db: Session = Depends(get_mysql_db)):
    """获取会话详情"""
    from ..models import ChatSession
    
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_dict()


@router.delete("/chat-sessions/{session_id}")
def delete_chat_session(session_id: str, db: Session = Depends(get_mysql_db)):
    """删除会话"""
    from ..models import ChatSession
    
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    db.delete(session)
    db.commit()
    return {"status": "deleted"}


@router.get("/chat-sessions/{session_id}/messages")
def get_chat_messages(session_id: str, db: Session = Depends(get_mysql_db)):
    """获取会话消息列表"""
    from ..models import ChatSession, ChatMessage
    
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at).all()
    
    return {"items": [m.to_dict() for m in messages]}


@router.post("/chat-sessions/{session_id}/messages")
def add_chat_message(
    session_id: str,
    data: ChatMessageCreate,
    db: Session = Depends(get_mysql_db)
):
    """添加消息到会话"""
    from ..models import ChatSession, ChatMessage
    import json as _json
    
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    message = ChatMessage(
        session_id=session_id,
        role=data.role,
        content=data.content,
        image_paths=_json.dumps(data.image_paths) if data.image_paths else None
    )
    db.add(message)
    
    # 更新会话时间
    from datetime import datetime
    session.updated_at = datetime.utcnow()
    
    # 自动更新标题：取第一条用户消息的前 50 字
    if data.role == "user" and session.title == "新对话" and data.content:
        session.title = data.content[:50]
    
    db.commit()
    db.refresh(message)
    

# ==================== Generic Upload API ====================

@router.post("/upload-file")
async def upload_generic_file(
    file: UploadFile = File(...)
):
    """
    通用文件上传接口 (用于 Article Agent 等临时文件上传)
    
    上传到 MinIO 的 uploads/ 目录
    返回 minio_path
    """
    from ..services.minio_service import minio_service
    import uuid
    import os
    
    import shutil
    
    # Generate unique object name
    ext = os.path.splitext(file.filename)[1]
    object_name = f"uploads/{uuid.uuid4().hex}_{file.filename}"
    
    logger.info(f"Generic upload started: {file.filename} ({file.content_type})")
    
    # Stream to temporary file first (avoid OOM)
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
        
    file_size = os.path.getsize(tmp_path)
    
    logger.info(f"Streamed to temp file: {tmp_path}")
    
    try:
        # Upload from path
        minio_path = minio_service.upload_from_path(
            tmp_path, 
            object_name, 
            file.content_type or "application/octet-stream"
        )
    finally:
        # Cleanup temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
            logger.info(f"Cleaned up temp file: {tmp_path}")
    
    if not minio_path:
        raise HTTPException(status_code=500, detail="Failed to upload file")
        
    return {
        "filename": file.filename,
        "minio_path": minio_path,
        "size": file_size,
        "content_type": file.content_type
    }


# ==================== Artifacts Serving ====================

@router.get("/artifacts/{path:path}")
async def serve_artifact(path: str):
    """
    Serve artifacts from /data/workspace/artifacts
    Used by vLLM to access media files ingested by Article Agent
    """
    from fastapi.responses import FileResponse
    import os
    
    artifact_root = "/data/workspace/artifacts"
    file_path = os.path.join(artifact_root, path)
    
    # Normalize path to prevent directory traversal
    file_path = os.path.normpath(file_path)
    
    if not file_path.startswith(artifact_root):
         raise HTTPException(status_code=403, detail="Access denied")
        
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Artifact not found: {path}")
        
    return FileResponse(file_path)
