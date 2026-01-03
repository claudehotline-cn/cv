import logging
import os
import json
from io import BytesIO
from typing import List, Dict, Any, Union
import asyncio
from concurrent.futures import ThreadPoolExecutor

from minio import Minio
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ...config.config import get_settings

_LOGGER = logging.getLogger(__name__)

# Global converter instance to avoid reloading models
_DOCLING_CONVERTER = None
_DOCLING_AVAILABLE = None

def get_docling_converter():
    """Lazy-load docling converter to avoid startup failures."""
    global _DOCLING_CONVERTER, _DOCLING_AVAILABLE
    
    if _DOCLING_AVAILABLE is None:
        try:
            from docling.document_converter import DocumentConverter
            _DOCLING_AVAILABLE = True
        except ImportError:
            _LOGGER.warning("Docling not available - will use PyMuPDF fallback")
            _DOCLING_AVAILABLE = False
    
    if not _DOCLING_AVAILABLE:
        return None
    
    if _DOCLING_CONVERTER is None:
        import os
        # Ensure HF mirror is set before Docling loads models
        if not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        from docling.document_converter import DocumentConverter
        _LOGGER.info(f"Initializing Docling converter (HF_ENDPOINT={os.environ.get('HF_ENDPOINT')})...")
        _DOCLING_CONVERTER = DocumentConverter()
    return _DOCLING_CONVERTER

def load_bytes_from_minio(path: str) -> bytes:
    """
    Read file bytes from MinIO (memory only, no disk write).
    
    Args:
        path: MinIO path, format 'article/uploads/xxx.pdf' or 'minio://bucket/key'
    
    Returns:
        File bytes content
    
    Raises:
        ValueError: Invalid path or file not found
    """
    _LOGGER.info(f"load_bytes_from_minio: {path}")
    
    # Parse path
    if path.startswith("minio://"):
        # minio://bucket/key
        parts = path[8:].split("/", 1)
        bucket, key = parts[0], parts[1] if len(parts) > 1 else ""
    elif "/" in path:
        # article/uploads/xxx.pdf or uploads/xxx.pdf
        settings = get_settings()
        bucket = settings.minio_bucket
        # 如果路径以 bucket 名开头，去掉它（避免重复）
        if path.startswith(f"{bucket}/"):
            key = path[len(bucket) + 1:]  # 去掉 "article/"
        else:
            key = path
    else:
        raise ValueError(f"Invalid MinIO path: {path}")
    
    # Create client
    settings = get_settings()
    client = Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure
    )
    
    # Read and properly close
    response = None
    try:
        response = client.get_object(bucket, key)
        data = response.read()
        _LOGGER.info(f"Loaded {len(data)} bytes from MinIO: {bucket}/{key}")
        return data
    finally:
        if response is not None:
            response.close()
            response.release_conn()

def parse_pdf_bytes_docling(pdf_bytes: bytes, filename: str = "doc.pdf") -> Dict[str, Any]:
    """
    Parse PDF bytes using Docling (memory stream).
    
    Returns:
        Dict with 'markdown', 'elements' (list of tables/images/formulas), 'headings', 'pages'
    """
    import os
    # Ensure HF mirror is available for any model downloads during parsing
    if not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    
    _LOGGER.info(f"parse_pdf_bytes_docling: {filename}, {len(pdf_bytes)} bytes (HF_ENDPOINT={os.environ.get('HF_ENDPOINT')})")
    
    converter = get_docling_converter()
    if converter is None:
        raise ImportError("Docling not available")
    
    try:
        from docling.datamodel.base_models import DocumentStream
        
        stream = BytesIO(pdf_bytes)
        source = DocumentStream(name=filename, stream=stream)
        
        result = converter.convert(source) 
        doc = result.document
        
        md_text = doc.export_to_markdown()
        _LOGGER.info(f"Docling parsed: {len(md_text)} chars")
        
        # 提取 elements (表格/图片/公式)
        elements = []
        headings = []
        
        # Docling document structure varies by version
        # Try to extract structured elements if available
        try:
            # Iterate document items if available
            if hasattr(doc, 'items') or hasattr(doc, 'body'):
                items = getattr(doc, 'items', None) or getattr(doc, 'body', [])
                for idx, item in enumerate(items if items else []):
                    item_type = getattr(item, 'type', None) or type(item).__name__
                    
                    # Tables
                    if 'table' in str(item_type).lower():
                        elements.append({
                            "element_id": f"tbl_{idx}",
                            "type": "table",
                            "content": str(item)[:500],  # Preview
                            "index": idx
                        })
                    # Images
                    elif 'image' in str(item_type).lower() or 'figure' in str(item_type).lower():
                        elements.append({
                            "element_id": f"img_{idx}",
                            "type": "image",
                            "content": getattr(item, 'caption', '') or '',
                            "index": idx
                        })
                    # Headings
                    elif 'heading' in str(item_type).lower() or 'title' in str(item_type).lower():
                        heading_text = getattr(item, 'text', '') or str(item)[:100]
                        headings.append(heading_text)
                    # Formulas/equations
                    elif 'formula' in str(item_type).lower() or 'equation' in str(item_type).lower():
                        elements.append({
                            "element_id": f"eq_{idx}",
                            "type": "formula",
                            "content": str(item)[:200],
                            "index": idx
                        })
        except Exception as e:
            _LOGGER.warning(f"Failed to extract elements from Docling doc: {e}")
        
        # Fallback: extract headings from markdown
        if not headings:
            import re
            headings = re.findall(r'^#{1,3}\s+(.+)$', md_text, re.MULTILINE)[:10]
        
        # 提取页数
        pages = 0
        try:
            if hasattr(result, 'pages'):
                pages = len(result.pages)
            elif hasattr(doc, 'pages'):
                pages = len(doc.pages)
            elif hasattr(result, 'metadata') and result.metadata:
                pages = result.metadata.get('page_count', 0)
        except:
            pass
        
        # Fallback: 用 PyMuPDF 获取页数
        if pages == 0:
            try:
                import fitz
                with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf_doc:
                    pages = len(pdf_doc)
            except:
                pass
        
        return {
            "markdown": md_text,
            "elements": elements,
            "headings": headings,
            "pages": pages
        }

    except Exception as e:
        _LOGGER.error(f"Docling parsing failed: {e}")
        raise

def chunk_text(text: str, chunk_size: int = 1200, chunk_overlap: int = 200) -> List[str]:
    """
    Split text into chunks using RecursiveCharacterTextSplitter.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )
    return splitter.split_text(text)

async def ingest_documents_tool(article_id: str, source_type: str, source_path: str) -> str:
    """
    Ingest a document: fetch -> parse -> chunk -> persist -> manifest.
    
    Args:
        article_id: The ID of the article being written.
        source_type: 'minio' or 'url'.
        source_path: MinIO path or HTTP URL.
        
    Returns:
        Path to the generated manifest.json.
    """
    import hashlib
    import json
    
    _LOGGER.info(f"ingest_documents_tool: {article_id}, {source_type}, {source_path}")
    
    # Variables for doc_id generation (will be set after fetch)
    doc_id = ""
    pages = 0
    
    # 2. Get article_dir (corpus paths will be set after doc_id is generated)
    from ...config.config import get_article_dir
    article_dir = get_article_dir(article_id)
    
    # 3. Fetch & Parse
    full_text = ""
    elements = []
    headings = []
    source_meta = {}
    
    try:
        if source_type == "minio":
            pdf_bytes = await asyncio.to_thread(load_bytes_from_minio, source_path)
            
            # 架构要求：doc_id = sha256(bucket:key:etag:size)
            settings = get_settings()
            etag = hashlib.md5(pdf_bytes).hexdigest()
            doc_id_seed = f"{settings.minio_bucket}:{source_path}:{etag}:{len(pdf_bytes)}"
            doc_id = "doc_" + hashlib.sha256(doc_id_seed.encode()).hexdigest()[:16]
            
            # Try Docling first
            try:
                parse_result = await asyncio.to_thread(parse_pdf_bytes_docling, pdf_bytes, source_path.split("/")[-1])
                full_text = parse_result.get("markdown", "")
                elements = parse_result.get("elements", [])
                headings = parse_result.get("headings", [])
                pages = parse_result.get("pages", 0)
            except Exception as e:
                _LOGGER.warning(f"Docling failed for {source_path}, falling back to PyMuPDF: {e}")
                # Fallback: PyMuPDF
                import fitz
                import pymupdf4llm
                with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                    full_text = pymupdf4llm.to_markdown(doc)
                    pages = len(doc)
            
            source_meta = {
                "type": "minio",
                "bucket": settings.minio_bucket,
                "key": source_path,
                "etag": etag,
                "size": len(pdf_bytes),
                "content_type": "application/pdf"
            }
            
        elif source_type == "url":
            # Use existing fetch logic
            from ..utils.files import fetch_url_with_images
            # This returns {"text": ..., "images": [...]}
            content = await asyncio.to_thread(fetch_url_with_images, source_path)
            full_text = content.get("text", "") or ""
            
            # 架构要求：URL 的 doc_id = sha256(url + content_hash)
            content_hash = hashlib.sha256(full_text.encode()).hexdigest()[:16]
            doc_id_seed = f"{source_path}:{content_hash}"
            doc_id = "doc_" + hashlib.sha256(doc_id_seed.encode()).hexdigest()[:16]
            
            # Extract headings from markdown for URLs
            import re
            headings = re.findall(r'^#{1,3}\s+(.+)$', full_text, re.MULTILINE)[:10]
            source_meta = {
                "type": "url",
                "url": source_path
            }
        else:
            return f"Error: Unsupported source type {source_type}"

    except Exception as e:
        _LOGGER.error(f"Ingest failed: {e}")
        return f"Error ingesting {source_path}: {str(e)}"

    # 4. 创建目录 (doc_id 现在已生成) - 使用 artifacts.py 的异步函数
    from ..utils.artifacts import ensure_corpus_dir
    corpus_dir, parsed_dir = await ensure_corpus_dir(article_id, doc_id)

    # 5. Chunking
    chunks = chunk_text(full_text)
    
    # 5. Persist
    
    # 5.1 full.md
    full_md_path = os.path.join(parsed_dir, "full.md")
    with open(full_md_path, "w", encoding="utf-8") as f:
        f.write(full_text)
    
    # 5.2 elements.jsonl (新增)
    elements_jsonl_path = os.path.join(parsed_dir, "elements.jsonl")
    with open(elements_jsonl_path, "w", encoding="utf-8") as f:
        for elem in elements:
            f.write(json.dumps(elem, ensure_ascii=False) + "\n")
    _LOGGER.info(f"Saved {len(elements)} elements to {elements_jsonl_path}")
        
    # 5.3 chunks.jsonl
    chunks_jsonl_path = os.path.join(corpus_dir, "chunks.jsonl")
    with open(chunks_jsonl_path, "w", encoding="utf-8") as f:
        for idx, chunk in enumerate(chunks):
            chunk_data = {
                "chunk_id": f"{doc_id}_c{idx}",
                "content": chunk,
                "metadata": {
                    "source": source_path,
                    "doc_id": doc_id,
                    "chunk_index": idx
                }
            }
            f.write(json.dumps(chunk_data, ensure_ascii=False) + "\n")
            
    # 5.4 Manifest (更新：包含 elements 和 headings)
    manifest = {
        "doc_id": doc_id,
        "article_id": article_id,
        "source_ref": source_meta,
        "paths": {
            "full_md": full_md_path,
            "chunks": chunks_jsonl_path,
            "elements": elements_jsonl_path
        },
        "headings": headings,
        "stats": {
            "pages": pages,
            "chunks": len(chunks),
            "chars": len(full_text),
            "elements": len(elements),
            "tables": sum(1 for e in elements if e.get("type") == "table"),
            "images": sum(1 for e in elements if e.get("type") == "image")
        },
        "quality_flags": []
    }
    
    manifest_path = os.path.join(corpus_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    
    # 5.5 Ingest Report (新增 - 采集报告)
    import datetime
    ingest_report = {
        "doc_id": doc_id,
        "article_id": article_id,
        "source": source_path,
        "source_type": source_type,
        "timestamp": datetime.datetime.now().isoformat(),
        "status": "success",
        "summary": f"Successfully ingested {source_path}",
        "stats": manifest["stats"],
        "headings_preview": headings[:5] if headings else [],
        "quality_flags": [],
        "errors": []
    }
    
    ingest_report_path = os.path.join(corpus_dir, "ingest_report.json")
    with open(ingest_report_path, "w", encoding="utf-8") as f:
        json.dump(ingest_report, f, ensure_ascii=False, indent=2)
    
    _LOGGER.info(f"Manifest saved: {manifest_path}, {len(chunks)} chunks, {len(elements)} elements")
    _LOGGER.info(f"Ingest report saved: {ingest_report_path}")
    return manifest_path


