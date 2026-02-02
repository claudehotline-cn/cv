"""文档分块器"""

import logging
import re
from typing import Any, List, Tuple
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class TextChunk:
    """文本分块"""
    content: str
    index: int
    metadata: dict[str, Any]


@dataclass
class ParentChildChunk:
    """父子分块结构"""
    content: str
    index: int
    metadata: dict[str, Any]
    is_parent: bool = False
    parent_index: int | None = None  # 子块指向父块的索引 (父块此字段为None)


class DocumentChunker:
    """文档分块器"""
    
    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        preprocess: bool = True,
    ):
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.preprocess = preprocess
        
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
    
    def chunk(self, content: str, metadata: dict[str, Any] | None = None) -> List[TextChunk]:
        """将文档内容分块 (标准分块)"""
        if not content or not content.strip():
            return []
        
        # 预处理：清理多余空白
        if self.preprocess:
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

    def hierarchical_chunk(
        self, 
        content: str, 
        metadata: dict[str, Any] | None = None,
        parent_size: int = 2000,
        parent_overlap: int = 200,
        child_size: int = 500,
        child_overlap: int = 50,
    ) -> Tuple[List[ParentChildChunk], List[ParentChildChunk]]:
        """
        父子分块 (Parent-Child Chunking)
        
        Returns:
            (parent_chunks, child_chunks) - 两个列表
            child_chunks 通过 parent_index 关联到 parent_chunks
        """
        if not content or not content.strip():
            return [], []
        
        if self.preprocess:
            content = self._preprocess(content)
        
        # 1. 创建父块分割器
        parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=parent_size,
            chunk_overlap=parent_overlap,
            length_function=len,
            separators=["\n\n", "\n", "。", ".", " ", ""],
        )
        
        # 2. 创建子块分割器
        child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_size,
            chunk_overlap=child_overlap,
            length_function=len,
            separators=["\n\n", "\n", "。", ".", " ", ""],
        )
        
        # 3. 分割父块
        parent_texts = parent_splitter.split_text(content)
        
        parent_chunks = []
        child_chunks = []
        child_global_index = 0
        
        for parent_idx, parent_text in enumerate(parent_texts):
            # 创建父块
            parent_chunk = ParentChildChunk(
                content=parent_text.strip(),
                index=parent_idx,
                metadata={
                    **(metadata or {}),
                    "chunk_type": "parent",
                    "parent_index": parent_idx,
                    "parent_total": len(parent_texts),
                },
                is_parent=True,
                parent_index=None,
            )
            parent_chunks.append(parent_chunk)
            
            # 4. 分割子块
            child_texts = child_splitter.split_text(parent_text)
            
            for local_idx, child_text in enumerate(child_texts):
                child_chunk = ParentChildChunk(
                    content=child_text.strip(),
                    index=child_global_index,
                    metadata={
                        **(metadata or {}),
                        "chunk_type": "child",
                        "parent_index": parent_idx,
                        "child_local_index": local_idx,
                        "children_in_parent": len(child_texts),
                    },
                    is_parent=False,
                    parent_index=parent_idx,
                )
                child_chunks.append(child_chunk)
                child_global_index += 1
        
        logger.info(f"Hierarchical split: {len(parent_chunks)} parents, {len(child_chunks)} children")
        return parent_chunks, child_chunks
    
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

    def _split_sentences(self, text: str) -> List[str]:
        """将文本分割成句子"""
        # 中英文句子分割
        pattern = r'(?<=[。！？.!?])\s*|\n+'
        sentences = re.split(pattern, text)
        # 过滤空句子并清理
        return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 5]

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        import numpy as np
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        dot = np.dot(v1, v2)
        norm = np.linalg.norm(v1) * np.linalg.norm(v2)
        return float(dot / norm) if norm > 0 else 0.0

    def semantic_chunk(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        similarity_threshold: float = 0.5,
        min_chunk_size: int = 200,
        max_chunk_size: int = 1500,
    ) -> List[TextChunk]:
        """
        语义分块 - 基于句子嵌入相似度
        
        Args:
            content: 文档内容
            metadata: 元数据
            similarity_threshold: 相似度阈值，低于此值则分割 (0.0-1.0)
            min_chunk_size: 最小块大小
            max_chunk_size: 最大块大小
            
        Returns:
            分块列表
        """
        if not content or not content.strip():
            return []
        
        if self.preprocess:
            content = self._preprocess(content)
        sentences = self._split_sentences(content)
        
        if len(sentences) <= 1:
            return [TextChunk(content=content, index=0, metadata=metadata or {})]
        
        # 批量嵌入句子
        from .embedder import embedding_service
        embeddings = embedding_service.embed_texts(sentences)
        
        # 计算相邻句子的相似度
        similarities = []
        for i in range(len(embeddings) - 1):
            sim = self._cosine_similarity(embeddings[i], embeddings[i + 1])
            similarities.append(sim)
        
        # 找到分割点 (相似度低于阈值的位置)
        breakpoints = []
        current_size = len(sentences[0])
        
        for i, sim in enumerate(similarities):
            current_size += len(sentences[i + 1])
            
            # 强制分割条件：达到最大长度
            if current_size >= max_chunk_size:
                breakpoints.append(i + 1)
                current_size = 0
            # 语义分割条件：相似度低于阈值 且 已达到最小长度
            elif sim < similarity_threshold and current_size >= min_chunk_size:
                breakpoints.append(i + 1)
                current_size = 0
        
        # 根据分割点构建块
        chunks = []
        start_idx = 0
        
        for bp in breakpoints:
            chunk_sentences = sentences[start_idx:bp]
            if chunk_sentences:
                chunk_text = " ".join(chunk_sentences)
                chunks.append(TextChunk(
                    content=chunk_text,
                    index=len(chunks),
                    metadata={
                        **(metadata or {}),
                        "chunk_type": "semantic",
                        "sentence_count": len(chunk_sentences),
                    }
                ))
            start_idx = bp
        
        # 添加最后一块
        if start_idx < len(sentences):
            remaining = sentences[start_idx:]
            chunks.append(TextChunk(
                content=" ".join(remaining),
                index=len(chunks),
                metadata={
                    **(metadata or {}),
                    "chunk_type": "semantic",
                    "sentence_count": len(remaining),
                }
            ))
        
        logger.info(f"Semantic split: {len(sentences)} sentences -> {len(chunks)} chunks (threshold={similarity_threshold})")
        return chunks

    def semantic_hierarchical_chunk(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        similarity_threshold: float = 0.5,
        parent_max_size: int = 2000,
        child_max_size: int = 500,
    ) -> Tuple[List[ParentChildChunk], List[ParentChildChunk]]:
        """
        语义父子分块 - 先语义分割成父块，再细分成子块
        
        Returns:
            (parent_chunks, child_chunks)
        """
        if not content or not content.strip():
            return [], []
        
        # 1. 语义分割成大块 (作为父块)
        semantic_chunks = self.semantic_chunk(
            content=content,
            metadata=metadata,
            similarity_threshold=similarity_threshold,
            min_chunk_size=500,
            max_chunk_size=parent_max_size,
        )
        
        # 2. 子块分割器
        child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_max_size,
            chunk_overlap=50,
            length_function=len,
            separators=["\n\n", "\n", "。", ".", " ", ""],
        )
        
        parent_chunks = []
        child_chunks = []
        child_global_index = 0
        
        for parent_idx, semantic_chunk in enumerate(semantic_chunks):
            # 创建父块
            parent_chunk = ParentChildChunk(
                content=semantic_chunk.content,
                index=parent_idx,
                metadata={
                    **(metadata or {}),
                    "chunk_type": "semantic_parent",
                    "parent_index": parent_idx,
                    "parent_total": len(semantic_chunks),
                },
                is_parent=True,
                parent_index=None,
            )
            parent_chunks.append(parent_chunk)
            
            # 分割子块
            child_texts = child_splitter.split_text(semantic_chunk.content)
            
            for local_idx, child_text in enumerate(child_texts):
                child_chunk = ParentChildChunk(
                    content=child_text.strip(),
                    index=child_global_index,
                    metadata={
                        **(metadata or {}),
                        "chunk_type": "semantic_child",
                        "parent_index": parent_idx,
                        "child_local_index": local_idx,
                    },
                    is_parent=False,
                    parent_index=parent_idx,
                )
                child_chunks.append(child_chunk)
                child_global_index += 1
        
        logger.info(f"Semantic hierarchical split: {len(parent_chunks)} parents, {len(child_chunks)} children")
        return parent_chunks, child_chunks


    def markdown_hierarchical_chunk(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        child_max_size: int = 500,
        child_overlap: int = 50,
    ) -> Tuple[List[ParentChildChunk], List[ParentChildChunk]]:
        """Markdown-aware parent/child chunking.

        Splits parents by markdown headings (`#`..`######`) and then splits each section into child chunks.
        Works even when PDF extraction flattens newlines by allowing headings preceded by whitespace or `>`.
        """
        if not content or not content.strip():
            return [], []

        text = content if not self.preprocess else self._preprocess(content)

        # Find heading lines, excluding fenced code blocks.
        in_code = False
        fence = None
        starts: list[int] = []
        offset = 0
        for line in text.splitlines(True):
            stripped = line.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                f = stripped[:3]
                if not in_code:
                    in_code = True
                    fence = f
                elif fence == f:
                    in_code = False
                    fence = None

            if not in_code:
                # Only treat real markdown headings at line start (after optional whitespace / blockquote prefix).
                if re.match(r"^\s*(?:>\s*)?#{1,6}\s+", line):
                    starts.append(offset)

            offset += len(line)

        if len(starts) < 2:
            return self.semantic_hierarchical_chunk(content=text, metadata=metadata)

        # Include any prefix text into the first section.
        if starts[0] > 0:
            starts[0] = 0

        parent_texts: list[str] = []
        for i, s in enumerate(starts):
            e = starts[i + 1] if i + 1 < len(starts) else len(text)
            seg = text[s:e].strip()
            if seg:
                parent_texts.append(seg)

        child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_max_size,
            chunk_overlap=child_overlap,
            length_function=len,
            separators=["\n\n", "\n", "。", ".", " ", ""],
        )

        parent_chunks: list[ParentChildChunk] = []
        child_chunks: list[ParentChildChunk] = []
        child_global_index = 0

        for parent_idx, parent_text in enumerate(parent_texts):
            parent_chunks.append(
                ParentChildChunk(
                    content=parent_text,
                    index=parent_idx,
                    metadata={
                        **(metadata or {}),
                        "chunk_type": "markdown_parent",
                        "parent_index": parent_idx,
                        "parent_total": len(parent_texts),
                    },
                    is_parent=True,
                    parent_index=None,
                )
            )

            child_texts = child_splitter.split_text(parent_text)
            for local_idx, child_text in enumerate(child_texts):
                child_chunks.append(
                    ParentChildChunk(
                        content=child_text.strip(),
                        index=child_global_index,
                        metadata={
                            **(metadata or {}),
                            "chunk_type": "markdown_child",
                            "parent_index": parent_idx,
                            "child_local_index": local_idx,
                        },
                        is_parent=False,
                        parent_index=parent_idx,
                    )
                )
                child_global_index += 1

        logger.info(f"Markdown hierarchical split: {len(parent_chunks)} parents, {len(child_chunks)} children")
        return parent_chunks, child_chunks


# 单例
document_chunker = DocumentChunker()
