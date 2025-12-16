"""文档分块器"""

import logging
import re
from typing import List
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class TextChunk:
    """文本分块"""
    content: str
    index: int
    metadata: dict


class DocumentChunker:
    """文档分块器"""
    
    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
    ):
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        
        # 使用LangChain的递归字符分割器
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=[
                "\n\n",  # 段落
                "\n",    # 换行
                "。",    # 中文句号
                ".",     # 英文句号
                "！",    # 中文感叹号
                "!",     # 英文感叹号
                "？",    # 中文问号
                "?",     # 英文问号
                "；",    # 中文分号
                ";",     # 英文分号
                " ",     # 空格
                "",      # 字符
            ],
        )
    
    def chunk(self, content: str, metadata: dict = None) -> List[TextChunk]:
        """将文档内容分块"""
        if not content or not content.strip():
            return []
        
        # 预处理：清理多余空白
        content = self._preprocess(content)
        
        # 分块
        texts = self.splitter.split_text(content)
        
        # 构建分块对象
        chunks = []
        for i, text in enumerate(texts):
            chunk = TextChunk(
                content=text.strip(),
                index=i,
                metadata={
                    **(metadata or {}),
                    "chunk_index": i,
                    "chunk_total": len(texts),
                }
            )
            chunks.append(chunk)
        
        logger.info(f"Split document into {len(chunks)} chunks")
        return chunks
    
    def _preprocess(self, content: str) -> str:
        """预处理文本"""
        # 移除多余空行
        content = re.sub(r'\n{3,}', '\n\n', content)
        # 移除多余空格
        content = re.sub(r' {2,}', ' ', content)
        # 移除行首行尾空格
        lines = [line.strip() for line in content.split('\n')]
        content = '\n'.join(lines)
        return content.strip()


# 单例
document_chunker = DocumentChunker()
