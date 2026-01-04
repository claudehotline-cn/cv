import logging
import os
import json
from io import BytesIO
from typing import List, Dict, Any, Union
import asyncio
from concurrent.futures import ThreadPoolExecutor

from minio import Minio
import hashlib
import base64
from langchain_core.messages import HumanMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ...config.llm_runtime import build_chat_llm, extract_text_content
from ...config.config import get_settings

async def _describe_image_with_vlm(image_bytes: bytes, document_context: str = "") -> str:
    """Use VLM to generate a detailed description of the image.
    
    Args:
        image_bytes: Raw image bytes
        document_context: Optional context about the document (title, headings, topic)
                         to help VLM better understand the image
    """
    try:
        # Validate and convert image format if needed
        processed_bytes = image_bytes
        mime_type = "image/jpeg"
        
        # Check if it's SVG (text-based format)
        if image_bytes[:100].lower().find(b'<svg') >= 0 or image_bytes[:100].lower().find(b'<?xml') >= 0:
            _LOGGER.info("Detected SVG format, converting to PNG...")
            try:
                import cairosvg
                # Run cairosvg in a thread to avoid blocking the event loop
                processed_bytes = await asyncio.to_thread(cairosvg.svg2png, bytestring=image_bytes)
                mime_type = "image/png"
                _LOGGER.info("Successfully converted SVG to PNG")
            except ImportError:
                _LOGGER.warning("cairosvg not installed, skipping SVG...")
                return "SVG image (无法转换为位图)"
            except Exception as svg_err:
                _LOGGER.warning(f"SVG conversion failed: {svg_err}")
                return "SVG image (转换失败)"
        
        # Validate it's a valid image using Pillow and re-encode to PNG
        # Run in a thread to avoid blocking CPU
        def _process_image_sync(data: bytes) -> bytes:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(data))
            img.verify()  # Verify it's a valid image
            
            # Re-open after verify as verify confirms content but consumes the fp
            img = Image.open(io.BytesIO(data))
            
            # Handle transparency/palette explicitly
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                # Defines a white background
                img = img.convert('RGBA')
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3]) # 3 is alpha channel
                img = background
            else:
                img = img.convert("RGB")
            
            output = io.BytesIO()
            img.save(output, format="PNG")
            return output.getvalue()

        try:
            processed_bytes = await asyncio.to_thread(_process_image_sync, processed_bytes)
            mime_type = "image/png"
        except Exception as img_err:
            _LOGGER.warning(f"Invalid image format: {img_err}")
            return ""
        
        # Build LLM (Settings will determine provider, e.g. Gemini/OpenAI)
        llm = build_chat_llm(task_name="ingest_vlm")
        
        # Prepare content
        image_b64 = base64.b64encode(processed_bytes).decode("utf-8")
        
        # Build context-aware prompt
        if document_context:
            prompt_text = f"""这张图片来自以下文档：
【文档上下文】{document_context}

请根据文档上下文，详细描述这张图片的内容。识别其中的关键元素、专业术语、图表结构或技术概念。如果图片是某种技术架构图、流程图、可视化图表，请明确指出其类型和用途。请用中文回答。"""
        else:
            prompt_text = "请详细描述这张图片的内容。识别其中的关键元素、文字、图表或人物。请用中文回答。"
        
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                },
            ]
        )
        
        # Invoke
        response = await llm.ainvoke([message])
        return extract_text_content(response)
        
    except Exception as e:
        _LOGGER.warning(f"Error in VLM call: {e}")
        return ""


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
                                "element_id": f"{doc_id}_pic_{pic_idx}",  # Use doc_id prefix for global uniqueness
                                "data": img_bytes,
                                "ext": img_format.lower(),
                                "alt": caption or f"Picture {pic_idx+1}",
                                "page": page_no,
                                "width": pil_image.width,
                                "height": pil_image.height
                            })
                            
                            # 同时添加到 elements 用于 elements.jsonl
                            elements.append({
                                "element_id": f"{doc_id}_pic_{pic_idx}",  # Use doc_id prefix for global uniqueness
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
                   # Convert Wikipedia thumbnail URLs to full-size URLs
                   # Pattern: .../thumb/X/YZ/Filename/XXXpx-Filename -> .../X/YZ/Filename
                   if "upload.wikimedia.org" in img_src and "/thumb/" in img_src:
                       import re
                       # Remove /thumb/ and the size suffix (e.g., /250px-...)
                       full_url = re.sub(r'/thumb(/[^/]+/[^/]+/[^/]+)/\d+px-[^/]+$', r'\1', img_src)
                       if full_url != img_src:
                           _LOGGER.info(f"Converted thumbnail URL to full-size: {img_src[:50]}... -> {full_url[:50]}...")
                           img_src = full_url
                   
                   # Store image info
                   extracted_images.append({
                       "src": img_src,
                       "alt": img.get("alt") or img.get("caption") or "",
                       "ext": img_src.split(".")[-1] if "." in img_src else "jpg",
                       "element_id": f"{doc_id}_img_{i}",  # Use doc_id prefix for global uniqueness
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
    
    seen_hashes = set()
    for img in extracted_images:
        # For PDF images (which have 'data' bytes)
        if "data" in img:
            img_filename = f"{img['element_id']}.{img.get('ext', 'png')}"
            img_path = os.path.join(assets_dir, img_filename)
            await save_image(img, img_path)
            
            # Update element with local path
            
            # ========== 核心变更: VLM Description + Dedup ==========
            visual_desc = ""
            
            # Deduplication Check
            img_hash = ""
            if "data" in img:
                 img_hash = hashlib.md5(img["data"]).hexdigest()
            elif "src" in img:
                 img_hash = hashlib.md5(img["src"].encode()).hexdigest()
                 # Try to fetch bytes for VLM if not present
                 from ..utils.files import fetch_image_bytes
                 try:
                     fetched_bytes = await asyncio.to_thread(fetch_image_bytes, img["src"])
                     if fetched_bytes:
                         img["data"] = fetched_bytes
                         # Update hash based on content if possible, or keep URL hash
                         # Better to keep URL hash for consistency with existing dedup
                         pass
                 except Exception as e:
                     _LOGGER.warning(f"Failed to fetch bytes for URL image {img['src']}: {e}")
            
            if img_hash:
                if img_hash in seen_hashes:
                    _LOGGER.info(f"Skipping duplicate image {img['element_id']} (hash={img_hash[:8]})")
                    continue
                seen_hashes.add(img_hash)
            
            # Reuse logic if already seen
            # We can't easily reuse across *different* pdfs unless we have a global store, 
            # but for now we dedup within this run or via simpler means.
            # Actually, let's generate description for ALL unique images.
            
            try:
                # 只有 PDF 提取的图片 (有二进制数据) 或者是有效的 URL 图片才进行识别
                # URL 图片暂不下载，跳过 VLM (或者如果必须，需要先下载)
                # 用户要求 "ingest 阶段识别"，通常指 PDF 里的图。URL 图如果有 alt 也可以，但最好也识别。
                # 这里为了性能，暂只对 PDF 提取的 img['data'] 做识别
                if "data" in img:
                     _LOGGER.info(f"Generating VLM description for image {img['element_id']}...")
                     # Build document context for better recognition
                     doc_context = ", ".join(headings[:5]) if headings else ""
                     visual_desc = await _describe_image_with_vlm(img["data"], document_context=doc_context)
                     if visual_desc:
                         _LOGGER.info(f"VLM Description for {img['element_id']}: {visual_desc[:50]}...")
            except Exception as vlm_err:
                _LOGGER.error(f"VLM generation failed for {img['element_id']}: {vlm_err}")
            
            elements.append({
                "element_id": img["element_id"],
                "type": "image",
                "content": img.get("alt", ""),
                "visual_description": visual_desc, # 新增字段
                "src": img_path, # Local absolute path
                "index": img.get("page", 0)
            })
        
        # For URL images (already have URL src)
        elif "src" in img:
             visual_desc = ""
             # Try to fetch bytes for VLM
             from ..utils.files import fetch_image_bytes
             try:
                 fetched_bytes = await asyncio.to_thread(fetch_image_bytes, img["src"])
                 if fetched_bytes:
                      _LOGGER.info(f"Generating VLM description for URL image {img['element_id']}...")
                      # Build document context for better recognition
                      doc_context = ", ".join(headings[:5]) if headings else ""
                      visual_desc = await _describe_image_with_vlm(fetched_bytes, document_context=doc_context)
                      if visual_desc:
                          _LOGGER.info(f"VLM Description for {img['element_id']}: {visual_desc[:50]}...")
             except Exception as e:
                 _LOGGER.warning(f"Failed to process URL image {img['src']} for VLM: {e}")

             elements.append({
                "element_id": img["element_id"],
                "type": "image",
                "content": img.get("caption", "") or img.get("alt", ""),
                "visual_description": visual_desc,
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


