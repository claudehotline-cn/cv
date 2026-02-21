"""向量化服务 - 使用Ollama embedding"""

import logging
from typing import List
import httpx

from langchain_ollama import OllamaEmbeddings

from ..config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """向量化服务"""
    
    def __init__(self):
        self.model = settings.embedding_model
        self.base_url = settings.ollama_base_url
        
        # 使用langchain-ollama
        self.embeddings = OllamaEmbeddings(
            model=self.model,
            base_url=self.base_url,
        )
        
        logger.info(f"Initialized embedding service: {self.model} @ {self.base_url}")
    
    def embed_text(self, text: str) -> List[float]:
        """将单个文本转换为向量"""
        if not text or not text.strip():
            raise ValueError("Empty text cannot be embedded")
        
        return self.embeddings.embed_query(text)
    
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """批量将文本转换为向量"""
        if not texts:
            return []
        
        # 过滤空文本
        valid_texts = [t for t in texts if t and t.strip()]
        if not valid_texts:
            return []
        
        return self.embeddings.embed_documents(valid_texts)
    
    @property
    def dimension(self) -> int:
        """返回向量维度"""
        return settings.vector_dimension


# 单例
embedding_service = EmbeddingService()
