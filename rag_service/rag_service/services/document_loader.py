"""文档加载器 - 支持多种格式"""

import logging
import tempfile
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field

import pdfplumber
from docx import Document as DocxDocument
import pandas as pd
import markdown

from ..config import settings
from .image_encoder import image_encoder

logger = logging.getLogger(__name__)


@dataclass
class LoadedDocument:
    """加载后的文档"""
    content: str
    metadata: dict
    images: List[dict] = field(default_factory=list)  # [{"data": bytes, "page": int, "name": str}, ...]
    

class DocumentLoader:
    """多格式文档加载器"""
    
    SUPPORTED_TYPES = {
        ".pdf": "pdf",
        ".docx": "word",
        ".doc": "word",
        ".xlsx": "excel",
        ".xls": "excel",
        ".md": "markdown",
        ".txt": "text",
    }
    
    @classmethod
    def get_file_type(cls, filename: str) -> Optional[str]:
        """获取文件类型"""
        suffix = Path(filename).suffix.lower()
        return cls.SUPPORTED_TYPES.get(suffix)
    
    @classmethod
    def is_supported(cls, filename: str) -> bool:
        """检查文件是否支持"""
        return cls.get_file_type(filename) is not None
    
    def load(self, file_path: str, filename: str) -> LoadedDocument:
        """加载文档"""
        file_type = self.get_file_type(filename)
        
        if file_type == "pdf":
            return self._load_pdf(file_path, filename)
        elif file_type == "word":
            return self._load_word(file_path, filename)
        elif file_type == "excel":
            return self._load_excel(file_path, filename)
        elif file_type == "markdown":
            return self._load_markdown(file_path, filename)
        elif file_type == "text":
            return self._load_text(file_path, filename)
        else:
            raise ValueError(f"Unsupported file type: {filename}")
    
    def _load_pdf(self, file_path: str, filename: str) -> LoadedDocument:
        """加载PDF文档"""
        logger.info(f"Loading PDF: {filename}")

        mode = (getattr(settings, "pdf_extractor", "marker") or "marker").strip().lower()

        if mode in ("marker", "auto"):
            # Prefer Marker for better structure.
            # Important: for中文 PDF，不要用默认的 ocr_alphanum_threshold=0.3；否则容易误判为乱码导致全量 OCR。
            try:
                from marker.converters.pdf import PdfConverter
                from marker.models import create_model_dict
                from marker.renderers.chunk import ChunkOutput

                def _html_to_text(html: str) -> str:
                    try:
                        from bs4 import BeautifulSoup

                        soup = BeautifulSoup(str(html or ""), "html.parser")
                        txt = soup.get_text("\n")
                    except Exception:
                        txt = str(html or "")

                    lines = [ln.strip() for ln in txt.splitlines()]
                    lines = [ln for ln in lines if ln]
                    return "\n".join(lines).strip()

                def _build_section_id_title_map(rendered: ChunkOutput) -> dict[str, str]:
                    m: dict[str, str] = {}
                    for b in rendered.blocks or []:
                        if str(getattr(b, "block_type", "")).lower() != "sectionheader":
                            continue
                        sid = str(getattr(b, "id", "") or "").strip()
                        if not sid:
                            continue
                        txt = _html_to_text(getattr(b, "html", ""))
                        if txt:
                            # Prefer the first line as heading text.
                            m[sid] = txt.split("\n", 1)[0].strip()
                    return m

                def _extract_outline_headings_from_chunk_output(rendered: ChunkOutput, id_to_title: dict[str, str]) -> list[tuple[int, str]]:
                    headings: list[tuple[int, str]] = []
                    last_path: list[tuple[int, str]] = []
                    for b in rendered.blocks or []:
                        hierarchy = getattr(b, "section_hierarchy", None) or None
                        if not hierarchy:
                            continue

                        # hierarchy value is a section header block id, not the title.
                        path: list[tuple[int, str]] = []
                        for k, v in hierarchy.items():
                            sid = str(v).strip()
                            if not sid:
                                continue
                            title = (id_to_title.get(sid) or sid).strip()
                            if not title:
                                continue
                            path.append((int(k), title))
                        path.sort(key=lambda x: x[0])

                        i = 0
                        while i < len(last_path) and i < len(path) and last_path[i] == path[i]:
                            i += 1
                        for lvl, title in path[i:]:
                            headings.append((max(1, min(6, int(lvl))), title))
                        last_path = path
                    return headings

                def _build_markdown_from_chunk_output(rendered: ChunkOutput, id_to_title: dict[str, str]) -> str:
                    md_lines: list[str] = []
                    last_path: list[tuple[int, str]] = []
                    for b in rendered.blocks or []:
                        hierarchy = getattr(b, "section_hierarchy", None) or None
                        if hierarchy:
                            path: list[tuple[int, str]] = []
                            for k, v in hierarchy.items():
                                sid = str(v).strip()
                                if not sid:
                                    continue
                                title = (id_to_title.get(sid) or sid).strip()
                                if not title:
                                    continue
                                path.append((int(k), title))
                            path.sort(key=lambda x: x[0])

                            i = 0
                            while i < len(last_path) and i < len(path) and last_path[i] == path[i]:
                                i += 1
                            for lvl, title in path[i:]:
                                md_lines.append("#" * max(1, min(6, int(lvl))) + " " + title)
                                md_lines.append("")
                            last_path = path

                        # Skip section header block body (already emitted as a heading).
                        if str(getattr(b, "block_type", "")).lower() == "sectionheader":
                            continue

                        txt = _html_to_text(getattr(b, "html", ""))
                        if txt:
                            md_lines.append(txt)
                            md_lines.append("")

                    return "\n".join(md_lines).strip()

                converter = PdfConverter(
                    artifact_dict=create_model_dict(),
                    renderer="marker.renderers.chunk.ChunkRenderer",
                    config={
                        "force_ocr": bool(getattr(settings, "pdf_marker_force_ocr", False)),
                        "ocr_alphanum_threshold": float(getattr(settings, "pdf_marker_ocr_alphanum_threshold", 0.0)),
                    },
                )
                rendered = None
                for attempt in range(2):
                    try:
                        rendered = converter(file_path)
                        break
                    except Exception as e:
                        msg = str(e)
                        if attempt == 0 and ("IncompleteRead" in msg or "Connection broken" in msg):
                            continue
                        raise

                if not isinstance(rendered, ChunkOutput):
                    raise ValueError(f"Unexpected marker output type: {type(rendered)}")

                id_to_title = _build_section_id_title_map(rendered)
                md_text = _build_markdown_from_chunk_output(rendered, id_to_title)
                outline_headings = _extract_outline_headings_from_chunk_output(rendered, id_to_title)

                if md_text and str(md_text).strip():
                    page_count = 0
                    try:
                        with pdfplumber.open(file_path) as pdf:
                            page_count = len(pdf.pages)
                    except Exception:
                        page_count = 0

                    images = image_encoder.extract_from_pdf(file_path) if settings.vlm_model else []
                    return LoadedDocument(
                        content=str(md_text),
                        metadata={
                            "source": filename,
                            "type": "pdf",
                            "pages": page_count,
                            "extraction": "marker",
                            "marker_renderer": "chunk",
                            "force_ocr": bool(getattr(settings, "pdf_marker_force_ocr", False)),
                            "outline_headings": [{"level": lvl, "title": title} for (lvl, title) in outline_headings],
                        },
                        images=[{"data": img[0], "page": img[1], "name": f"page_{img[1]}_img"} for img in images],
                    )
            except Exception as e:
                logger.warning(f"Marker PDF->chunk failed for {filename}, falling back to pdfplumber: {e}")

            if mode == "marker":
                # marker 模式下 marker 失败才会继续 fallback
                pass
            else:
                # auto 模式下 marker 失败也会 fallback
                pass

        # Fallback: pdfplumber text extraction
        text_parts = []
        page_count = 0
        try:
            with pdfplumber.open(file_path) as pdf:
                page_count = len(pdf.pages)
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(f"[Page {i+1}]\n{page_text}")

                    tables = page.extract_tables()
                    for table in tables:
                        if table:
                            table_text = self._table_to_text(table)
                            text_parts.append(f"[Table on Page {i+1}]\n{table_text}")
        except Exception as e:
            logger.error(f"Error loading PDF {filename}: {e}")
            raise

        content = "\n\n".join(text_parts)
          
        # 提取图片
        images = image_encoder.extract_from_pdf(file_path) if settings.vlm_model else []
          
        return LoadedDocument(
            content=content,
            metadata={"source": filename, "type": "pdf", "pages": page_count, "extraction": "pdfplumber"},
            images=[{"data": img[0], "page": img[1], "name": f"page_{img[1]}_img"} for img in images]
        )
    
    def _load_word(self, file_path: str, filename: str) -> LoadedDocument:
        """加载Word文档"""
        logger.info(f"Loading Word: {filename}")
        
        suffix = Path(filename).suffix.lower()
        
        # 处理旧版 .doc 格式
        if suffix == ".doc":
            return self._load_legacy_doc(file_path, filename)
        
        # 处理 .docx 格式
        content = ""
        try:
            doc = DocxDocument(file_path)
            paragraphs = []
            
            for para in doc.paragraphs:
                if para.text.strip():
                    # 处理标题样式
                    if para.style.name.startswith('Heading'):
                        level = para.style.name.replace('Heading ', '')
                        try:
                            paragraphs.append(f"{'#' * int(level)} {para.text}")
                        except ValueError:
                            paragraphs.append(para.text)
                    else:
                        paragraphs.append(para.text)
            
            # 提取表格
            for table in doc.tables:
                table_data = []
                for row in table.rows:
                    row_data = [cell.text.strip() for cell in row.cells]
                    table_data.append(row_data)
                if table_data:
                    paragraphs.append(self._table_to_text(table_data))

            content = "\n\n".join(paragraphs)
                     
        except Exception as e:
            logger.error(f"Error loading Word {filename}: {e}")
            raise
        
        # 提取图片
        images = image_encoder.extract_from_docx(file_path) if settings.vlm_model else []
        
        return LoadedDocument(
            content=content,
            metadata={"source": filename, "type": "word"},
            images=[{"data": img[0], "page": img[1], "name": f"word_img_{i}"} for i, img in enumerate(images)]
        )
    
    def _load_legacy_doc(self, file_path: str, filename: str) -> LoadedDocument:
        """加载旧版 .doc 格式文档（使用 antiword）"""
        import subprocess
        
        try:
            # 尝试使用 antiword 提取文本
            result = subprocess.run(
                ['antiword', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                content = result.stdout
                if content.strip():
                    return LoadedDocument(
                        content=content,
                        metadata={"source": filename, "type": "doc"}
                    )
            
            # antiword 失败，尝试使用 catdoc
            result = subprocess.run(
                ['catdoc', file_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout.strip():
                return LoadedDocument(
                    content=result.stdout,
                    metadata={"source": filename, "type": "doc"}
                )
            
            # 两种方法都失败
            raise ValueError(
                f"无法解析 .doc 文件 '{filename}'。请尝试将文件另存为 .docx 格式后重新上传。"
            )
            
        except FileNotFoundError:
            raise ValueError(
                f"不支持旧版 .doc 格式文件 '{filename}'。请将文件另存为 .docx 格式后重新上传。"
            )
        except subprocess.TimeoutExpired:
            raise ValueError(f"处理 .doc 文件 '{filename}' 超时")
    
    def _load_excel(self, file_path: str, filename: str) -> LoadedDocument:
        """加载Excel文档"""
        logger.info(f"Loading Excel: {filename}")
        
        try:
            # 读取所有sheet
            xlsx = pd.ExcelFile(file_path)
            all_content = []
            
            for sheet_name in xlsx.sheet_names:
                df = pd.read_excel(xlsx, sheet_name=sheet_name)
                if not df.empty:
                    all_content.append(f"[Sheet: {sheet_name}]")
                    # 填充空值
                    df = df.fillna('')  # 将NaN替换为空字符串
                    # 将Unnamed列名替换为空字符串
                    df.columns = ['' if str(col).startswith('Unnamed:') else col for col in df.columns]
                    all_content.append(df.to_string(index=False))
                    
        except Exception as e:
            logger.error(f"Error loading Excel {filename}: {e}")
            raise
        
        content = "\n\n".join(all_content)
        return LoadedDocument(
            content=content,
            metadata={"source": filename, "type": "excel", "sheets": len(xlsx.sheet_names)}
        )
    
    def _load_markdown(self, file_path: str, filename: str) -> LoadedDocument:
        """加载Markdown文档"""
        logger.info(f"Loading Markdown: {filename}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Error loading Markdown {filename}: {e}")
            raise
        
        return LoadedDocument(
            content=content,
            metadata={"source": filename, "type": "markdown"}
        )
    
    def _load_text(self, file_path: str, filename: str) -> LoadedDocument:
        """加载纯文本文档"""
        logger.info(f"Loading Text: {filename}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # 尝试其他编码
            with open(file_path, 'r', encoding='gbk') as f:
                content = f.read()
        
        return LoadedDocument(
            content=content,
            metadata={"source": filename, "type": "text"}
        )
    
    def _table_to_text(self, table: List[List[str]]) -> str:
        """将表格转换为文本"""
        if not table:
            return ""
        
        # 使用Markdown表格格式
        lines = []
        for i, row in enumerate(table):
            line = "| " + " | ".join(str(cell) if cell else "" for cell in row) + " |"
            lines.append(line)
            if i == 0:
                # 添加表头分隔符
                separator = "| " + " | ".join("---" for _ in row) + " |"
                lines.append(separator)
        
        return "\n".join(lines)


# 单例
document_loader = DocumentLoader()
