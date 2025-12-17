"""API路由定义"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl
from typing import List, Optional
import tempfile
import os
import logging

from ..database import get_mysql_db, MySQLSessionLocal
from ..models import KnowledgeBase, Document
from ..services.document_loader import document_loader
from ..services.web_crawler import web_crawler
from ..services.chunker import document_chunker
from ..services.embedder import embedding_service
from ..services.vector_store import vector_store
from ..services.retriever import rag_retriever
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Schemas ====================

class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    chunk_size: Optional[int] = 500
    chunk_overlap: Optional[int] = 50


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


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


# ==================== Helpers ====================

def update_kb_document_count(db: Session, kb_id: int):
    """更新知识库文档计数 (计算所有非软删除的文档)"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if kb:
        kb.document_count = db.query(Document).filter(
            Document.knowledge_base_id == kb.id
        ).count()
        db.commit()


# ==================== Document APIs ====================

@router.get("/knowledge-bases/{kb_id}/documents")
def list_documents(kb_id: int, db: Session = Depends(get_mysql_db)):
    """获取知识库的文档列表"""
    docs = db.query(Document).filter(Document.knowledge_base_id == kb_id).all()
    return {"items": [doc.to_dict() for doc in docs]}


def process_document_async(document_id: int, file_path: str, filename: str):
    """异步处理文档"""
    db = MySQLSessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return
        
        doc.status = "processing"
        db.commit()
        
        # 加载文档
        loaded = document_loader.load(file_path, filename)
        
        # 获取知识库配置
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.knowledge_base_id).first()
        
        # 分块
        from ..services.chunker import DocumentChunker
        chunker = DocumentChunker(
            chunk_size=kb.chunk_size if kb else 500,
            chunk_overlap=kb.chunk_overlap if kb else 50,
        )
        chunks = chunker.chunk(loaded.content, loaded.metadata)
        
        # 向量化并存储
        if chunks:
            texts = [c.content for c in chunks]
            embeddings = embedding_service.embed_texts(texts)
            
            vector_data = [
                (c.index, c.content, emb, c.metadata)
                for c, emb in zip(chunks, embeddings)
            ]
            vector_store.store_vectors(document_id, vector_data)
        
        # 更新文档状态
        doc.chunk_count = len(chunks)
        doc.status = "completed"
        db.commit()
        
        logger.info(f"Document {document_id} processed: {len(chunks)} chunks")
        
    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.status = "failed"
            doc.error_message = str(e)
            db.commit()
    finally:
        db.close()
        # 清理临时文件 (原件已存储在 MinIO)
        if os.path.exists(file_path):
            os.remove(file_path)


@router.post("/knowledge-bases/{kb_id}/documents/upload")
async def upload_document(
    kb_id: int,
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
    
    # 同时保存到临时目录用于处理
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    
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
    
    # 后台处理 (使用临时文件路径)
    background_tasks.add_task(process_document_async, doc.id, tmp_path, file.filename)
    
    return doc.to_dict()


@router.post("/knowledge-bases/{kb_id}/documents/import-url")
async def import_url(
    kb_id: int,
    data: URLImportRequest,
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
    
    # 保存内容到临时文件并处理
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode='w', encoding='utf-8') as tmp:
        tmp.write(page.content)
        tmp_path = tmp.name
    
    background_tasks.add_task(process_document_async, doc.id, tmp_path, f"{page.title}.txt")
    
    return doc.to_dict()


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


# ==================== Chat API ====================

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
    # 获取检索结果（同步调用）
    results = rag_retriever.retrieve(
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_mysql_db),
):
    """
    触发构建知识图谱任务
    """
    # 检查知识库是否存在已解析的文档
    # 这里简化处理，以后台任务运行
    background_tasks.add_task(_run_graph_build_task, kb_id)
    
    return {"message": "Graph build task started", "kb_id": kb_id}

async def _run_graph_build_task(kb_id: int):
    """后台运行图构建 - 从 MinIO 下载原始文档构建"""
    try:
        from ..database import get_mysql_session
        from ..services.graph_builder import graph_builder
        from ..services.document_loader import document_loader
        from ..services.minio_service import minio_service
        from langchain_core.documents import Document as LangChainDocument
        
        logger.info(f"Starting graph build for KB {kb_id} (from MinIO)")
        
        lc_docs = []
        temp_files = []  # 记录需要清理的临时文件
        
        with get_mysql_session() as mysql_db:
            docs = mysql_db.query(Document).filter(Document.knowledge_base_id == kb_id).all()
            
            if not docs:
                logger.warning(f"No documents found for KB {kb_id}")
                return
            
            for doc in docs:
                try:
                    if not doc.file_path:
                        logger.warning(f"No file_path for doc {doc.id}")
                        continue
                    
                    # 从 MinIO 下载文件
                    tmp_path = minio_service.download_file(doc.file_path)
                    if not tmp_path:
                        logger.warning(f"Failed to download from MinIO: {doc.file_path}")
                        continue
                    
                    temp_files.append(tmp_path)
                    
                    # 如果文件名没有扩展名（如网页导入），尝试添加扩展名
                    filename_for_loader = doc.filename
                    if not os.path.splitext(doc.filename)[1] and doc.file_path:
                        ext = os.path.splitext(doc.file_path)[1]
                        if ext:
                            filename_for_loader += ext
                    
                    # 加载文档内容
                    loaded = document_loader.load(tmp_path, filename_for_loader)
                    
                    # 将完整文档拆分为较大的块
                    content = loaded.content
                    chunk_size = 3000
                    
                    for i in range(0, len(content), chunk_size):
                        chunk = content[i:i+chunk_size]
                        if len(chunk.strip()) > 100:
                            lc_docs.append(
                                LangChainDocument(
                                    page_content=chunk,
                                    metadata={"source": doc.filename, "doc_id": doc.id, "chunk": i // chunk_size}
                                )
                            )
                    
                    logger.info(f"Loaded {doc.filename}: {len(content)} chars -> {(len(content) // chunk_size) + 1} large chunks")
                        
                except Exception as e:
                    logger.error(f"Error loading doc {doc.id} ({doc.filename}): {e}")
        
        if lc_docs:
            logger.info(f"Building graph from {len(lc_docs)} document chunks (large chunks for better context)")
            await graph_builder.build_from_documents(lc_docs)
            logger.info(f"Graph build finished for KB {kb_id}")
        else:
            logger.warning(f"No valid documents loaded for KB {kb_id}")
        
        # 清理临时文件
        for tmp_path in temp_files:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except:
                pass
                
    except Exception as e:
        logger.error(f"Error in graph build task: {e}")
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

