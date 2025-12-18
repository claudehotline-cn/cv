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


# ==================== Document APIs ====================

@router.get("/knowledge-bases/{kb_id}/documents")
def list_documents(kb_id: int, db: Session = Depends(get_mysql_db)):
    """获取知识库的文档列表"""
    docs = db.query(Document).filter(Document.knowledge_base_id == kb_id).all()
    return {"items": [doc.to_dict() for doc in docs]}


def process_document_async(document_id: int, file_path: str, filename: str):
    """异步处理文档 (使用父子索引策略)"""
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
        
        # 语义父子分块 (Semantic Hierarchical Chunking)
        from ..services.chunker import DocumentChunker
        chunker = DocumentChunker()
        
        parent_chunks, child_chunks = chunker.semantic_hierarchical_chunk(
            content=loaded.content,
            metadata=loaded.metadata,
            similarity_threshold=0.5,  # 相似度低于0.5时分割
            parent_max_size=kb.chunk_size * 4 if kb else 2000,
            child_max_size=kb.chunk_size if kb else 500,
        )
        
        # 向量化
        if parent_chunks or child_chunks:
            # Embed 父块
            parent_texts = [p.content for p in parent_chunks]
            parent_embeddings = embedding_service.embed_texts(parent_texts) if parent_texts else []
            
            # Embed 子块
            child_texts = [c.content for c in child_chunks]
            child_embeddings = embedding_service.embed_texts(child_texts) if child_texts else []
            
            # 构建存储数据
            parent_data = [
                (p.index, p.content, emb, p.metadata)
                for p, emb in zip(parent_chunks, parent_embeddings)
            ]
            
            child_data = [
                (c.index, c.content, emb, c.metadata, c.parent_index)
                for c, emb in zip(child_chunks, child_embeddings)
            ]
            
            # 存储
            vector_store.store_hierarchical_vectors(document_id, parent_data, child_data)
        
        # 更新文档状态
        total_chunks = len(parent_chunks) + len(child_chunks)
        doc.chunk_count = total_chunks
        doc.status = "completed"
        db.commit()
        
        logger.info(f"Document {document_id} processed: {len(parent_chunks)} parents + {len(child_chunks)} children = {total_chunks} chunks")
        
    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
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

class StreamChatRequest(BaseModel):
    query: str
    knowledge_base_id: Optional[int] = None
    top_k: Optional[int] = 5
    session_id: Optional[str] = None  # 用于对话历史


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
    from langchain_ollama import ChatOllama
    from langchain_core.prompts import ChatPromptTemplate
    import json
    
    async def generate():
        try:
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
            
            # 3. 获取对话历史
            from ..services.conversation_memory import conversation_memory
            history_text = ""
            if data.session_id:
                history_text = conversation_memory.get_history_text(data.session_id)
            
            # 4. 构建上下文
            context = "\n\n".join([
                f"[{i+1}] {r.content}" 
                for i, r in enumerate(results)
            ])
            
            # 5. 流式生成回答
            llm = ChatOllama(
                model=settings.llm_model,
                base_url=settings.ollama_base_url,
                temperature=0.7,
            )
            
            # 构建包含历史的提示
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
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("human", "{query}")
            ])
            
            chain = prompt | llm
            
            # 收集完整回答用于保存历史
            full_answer = ""
            
            async for chunk in chain.astream({"context": context, "query": data.query, "history": history_text}):
                content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                if content:
                    full_answer += content
                    yield f"data: {json.dumps({'type': 'token', 'content': content}, ensure_ascii=False)}\n\n"
            
            # 6. 保存对话历史
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
    
    background_tasks.add_task(_run_rebuild_vectors_task, kb_id)
    
    return {
        "message": "Rebuild vectors task started",
        "kb_id": kb_id,
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
