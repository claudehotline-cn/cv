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
    """Lazy-load docling converter with picture extraction enabled."""
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
        
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import InputFormat
        
        # Configure pipeline to extract pictures
        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_picture_images = True  # Enable image extraction
        pipeline_options.images_scale = 2.0  # Higher quality images
        
        _LOGGER.info(f"Initializing Docling converter with picture extraction (HF_ENDPOINT={os.environ.get('HF_ENDPOINT')})...")
        _DOCLING_CONVERTER = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
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
        Dict with 'markdown', 'elements' (list of tables/images/formulas), 'headings', 'pages', 'pictures'
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
        pictures = []  # 新增：存储提取的图片数据
        
        # ========== 提取图片 (纯 Docling 方式) ==========
        try:
            if hasattr(doc, 'pictures') and doc.pictures:
                _LOGGER.info(f"Docling found {len(doc.pictures)} pictures")
                # Docling v2.66: doc.pictures is a LIST, PictureItem uses get_image() method
                for pic_idx, pic_item in enumerate(doc.pictures):
                    try:
                        # 使用 get_image() 方法获取 PIL Image - 需要传入 doc 参数
                        pil_image = None
                        if hasattr(pic_item, 'get_image'):
                            try:
                                pil_image = pic_item.get_image(doc)
                            except Exception as img_err:
                                _LOGGER.debug(f"get_image() failed for pic {pic_idx}: {img_err}")
                        
                        if pil_image:
                            # 转换为 bytes
                            from PIL import Image
                            import io
                            img_buffer = io.BytesIO()
                            img_format = getattr(pil_image, 'format', None) or "PNG"
                            pil_image.save(img_buffer, format=img_format)
                            img_bytes = img_buffer.getvalue()
                            
                            # 获取页码 (如果有)
                            page_no = 0
                            if hasattr(pic_item, 'prov') and pic_item.prov:
                                prov_list = pic_item.prov if isinstance(pic_item.prov, list) else [pic_item.prov]
                                for prov in prov_list:
                                    if hasattr(prov, 'page_no'):
                                        page_no = prov.page_no
                                        break
                            
                            # 获取 caption
                            caption = ""
                            if hasattr(pic_item, 'caption_text'):
                                try:
                                    caption = pic_item.caption_text(doc) or ""
                                except:
                                    pass
                            
                            pictures.append({
                                "element_id": f"pic_{pic_idx}",
                                "data": img_bytes,
                                "ext": img_format.lower(),
                                "alt": caption or f"Picture {pic_idx+1}",
                                "page": page_no,
                                "width": pil_image.width,
                                "height": pil_image.height
                            })
                            
                            # 同时添加到 elements 用于 elements.jsonl
                            elements.append({
                                "element_id": f"pic_{pic_idx}",
                                "type": "image",
                                "content": caption,
                                "index": len(elements),
                                "page": page_no
                            })
                        else:
                            _LOGGER.debug(f"No image data for picture {pic_idx}")
                    except Exception as pic_err:
                        _LOGGER.warning(f"Failed to extract picture {pic_idx}: {pic_err}")
                        
            _LOGGER.info(f"Extracted {len(pictures)} pictures from Docling")
        except Exception as e:
            _LOGGER.warning(f"Failed to extract pictures from Docling doc: {e}")
        
        # ========== 提取表格/标题/公式 ==========
        try:
            # 从 tables - 可能也是 list
            if hasattr(doc, 'tables') and doc.tables:
                tables_iter = enumerate(doc.tables) if isinstance(doc.tables, list) else doc.tables.items()
                for tbl_id, tbl_item in (tables_iter if not isinstance(doc.tables, list) else [(i, t) for i, t in enumerate(doc.tables)]):
                    elements.append({
                        "element_id": f"tbl_{tbl_id}",
                        "type": "table",
                        "content": str(tbl_item)[:500],
                        "index": len(elements)
                    })
            
            # 从 body 提取标题
            if hasattr(doc, 'body') and doc.body:
                for idx, item in enumerate(doc.body):
                    item_type = getattr(item, 'label', None) or type(item).__name__
                    if 'heading' in str(item_type).lower() or 'title' in str(item_type).lower():
                        heading_text = getattr(item, 'text', '') or str(item)[:100]
                        headings.append(heading_text)
        except Exception as e:
            _LOGGER.warning(f"Failed to extract elements from Docling doc: {e}")
        
        # Fallback: extract headings from markdown
        if not headings:
            import re
            headings = re.findall(r'^#{1,3}\s+(.+)$', md_text, re.MULTILINE)[:10]
        
        # 提取页数
        pages = 0
        try:
            if hasattr(doc, 'pages') and doc.pages:
                pages = len(doc.pages)
            elif hasattr(result, 'pages'):
                pages = len(result.pages)
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
            "pages": pages,
            "pictures": pictures  # 新增：返回图片数据
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
    extracted_images = []  # List of dicts: {data (bytes), ext, alt, page/index, element_id, src (if URL)}
    
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
                # Docling extracted elements (tables, images, etc.)
                docling_elements = parse_result.get("elements", [])
                headings = parse_result.get("headings", [])
                pages = parse_result.get("pages", 0)
                
                # 使用 Docling 提取的图片 (纯 Docling 方式)
                docling_pictures = parse_result.get("pictures", [])
                if docling_pictures:
                    extracted_images.extend(docling_pictures)
                    _LOGGER.info(f"Collected {len(docling_pictures)} images from Docling")
                
                # 合并所有 elements
                elements.extend(docling_elements)
                        
            except Exception as e:
                _LOGGER.warning(f"Docling failed for {source_path}, falling back to PyMuPDF: {e}")
                # Fallback: PyMuPDF for text
                import fitz
                import pymupdf4llm
                with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                    full_text = pymupdf4llm.to_markdown(doc)
                    pages = len(doc)
                
                # Fallback: PyMuPDF for images (only when Docling fails)
                from ..utils.files import extract_images_from_pdf_bytes
                pdf_images = await asyncio.to_thread(extract_images_from_pdf_bytes, pdf_bytes)
                if pdf_images:
                    extracted_images.extend(pdf_images)
                    _LOGGER.info(f"Collected {len(pdf_images)} images from PyMuPDF fallback")
            
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
            
            # Process URL images
            url_images = content.get("images", [])
            _LOGGER.info(f"URL fetch returned {len(url_images)} images from {source_path}")
            
            for i, img in enumerate(url_images):
                img_src = img.get("src")
                if img_src:
                   # Store image info (we don't download URL images to disk yet to save time, unless needed)
                   # But for consistency, let's treat them as elements. 
                   # Since Illustrator works with local files or accessible URLs, we keep URL.
                   extracted_images.append({
                       "src": img_src,
                       "alt": img.get("alt") or img.get("caption") or "",
                       "ext": img_src.split(".")[-1] if "." in img_src else "jpg",
                       "element_id": f"img_url_{i}",
                       "caption": img.get("context", "")
                   })
            
            if extracted_images:
                _LOGGER.info(f"Collected {len(extracted_images)} URL images")
            
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
    assets_dir = os.path.join(corpus_dir, "assets")
    await asyncio.to_thread(os.makedirs, assets_dir, exist_ok=True)

    # 4.1 Save Images to Assets (async file writes)
    async def save_image(img_data: dict, save_path: str):
        def _write():
            with open(save_path, "wb") as f:
                f.write(img_data["data"])
        await asyncio.to_thread(_write)
    
    for img in extracted_images:
        # For PDF images (which have 'data' bytes)
        if "data" in img:
            img_filename = f"{img['element_id']}.{img.get('ext', 'png')}"
            img_path = os.path.join(assets_dir, img_filename)
            await save_image(img, img_path)
            
            # Update element with local path
            elements.append({
                "element_id": img["element_id"],
                "type": "image",
                "content": img.get("alt", ""),
                "src": img_path, # Local absolute path
                "index": img.get("page", 0)
            })
        
        # For URL images (already have URL src)
        elif "src" in img:
             elements.append({
                "element_id": img["element_id"],
                "type": "image",
                "content": img.get("caption", "") or img.get("alt", ""),
                "src": img["src"], # Remote URL
                "index": 0
            })

    # 5. Chunking
    chunks = chunk_text(full_text)
    
    # 5. Persist (使用异步文件写入避免 BlockingError)
    
    def _write_text_file(path: str, content: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    
    def _write_json_file(path: str, data: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _write_jsonl_file(path: str, items: list):
        with open(path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    # 5.1 full.md
    full_md_path = os.path.join(parsed_dir, "full.md")
    await asyncio.to_thread(_write_text_file, full_md_path, full_text)
    
    # 5.2 elements.jsonl (新增)
    elements_jsonl_path = os.path.join(parsed_dir, "elements.jsonl")
    await asyncio.to_thread(_write_jsonl_file, elements_jsonl_path, elements)
    _LOGGER.info(f"Saved {len(elements)} elements to {elements_jsonl_path} (including {len(extracted_images)} images)")
        
    # 5.3 chunks.jsonl
    chunks_jsonl_path = os.path.join(corpus_dir, "chunks.jsonl")
    chunk_items = []
    for idx, chunk in enumerate(chunks):
        chunk_items.append({
            "chunk_id": f"{doc_id}_c{idx}",
            "content": chunk,
            "metadata": {
                "source": source_path,
                "doc_id": doc_id,
                "chunk_index": idx
            }
        })
    await asyncio.to_thread(_write_jsonl_file, chunks_jsonl_path, chunk_items)
            
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
    await asyncio.to_thread(_write_json_file, manifest_path, manifest)
    
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
    await asyncio.to_thread(_write_json_file, ingest_report_path, ingest_report)
    
    _LOGGER.info(f"Manifest saved: {manifest_path}, {len(chunks)} chunks, {len(elements)} elements")
    _LOGGER.info(f"Ingest report saved: {ingest_report_path}")
    return manifest_path


