"""
多模态混合检索器

功能：
- 文本检索 (继承现有 RAG 逻辑)
- 图像检索 (基于图像描述向量)
- 语音/视频检索 (基于转写文本)
- 跨模态融合 (RRF)
- 多模态问答
"""

import logging
from typing import List, Optional, Union
from dataclasses import dataclass, field

from ..config import settings
from .retriever import rag_retriever, RAGResponse
from .vector_store import vector_store, SearchResult
from .embedder import embedding_service
from .vlm_service import vlm_service
from .image_encoder import image_encoder

logger = logging.getLogger(__name__)


@dataclass
class MultiModalSearchResult:
    """多模态检索结果"""
    text_results: List[SearchResult] = field(default_factory=list)
    image_results: List[dict] = field(default_factory=list)  # 图像检索结果
    audio_results: List[dict] = field(default_factory=list)  # 音频检索结果
    video_results: List[dict] = field(default_factory=list)  # 视频检索结果


@dataclass
class MultiModalResponse:
    """多模态问答响应"""
    answer: str
    sources: List[dict]
    images: List[dict]  # 相关图像
    has_multimodal_context: bool


class MultiModalRetriever:
    """多模态混合检索器"""
    
    def __init__(self):
        self.text_retriever = rag_retriever
        
        logger.info("Initialized multimodal retriever")
    
    async def retrieve(
        self,
        query: str,
        images: Optional[List[bytes]] = None,
        knowledge_base_id: Optional[int] = None,
        top_k: int = 5,
        include_images: bool = True,
        include_audio: bool = True,
        include_video: bool = True,
    ) -> MultiModalSearchResult:
        """
        多模态混合检索
        
        Args:
            query: 文本查询
            images: 可选的图像查询
            knowledge_base_id: 知识库 ID
            top_k: 返回结果数
            include_images: 是否检索图像
            include_audio: 是否检索音频
            include_video: 是否检索视频
            
        Returns:
            MultiModalSearchResult 包含各模态检索结果
        """
        result = MultiModalSearchResult()
        
        # 1. 文本检索 (使用现有 RAG retriever)
        text_results = await self.text_retriever.retrieve(
            query=query,
            knowledge_base_id=knowledge_base_id,
            top_k=top_k
        )
        result.text_results = text_results
        
        # 2. 如果提供了图像查询，分析图像并扩展查询
        if images:
            for img in images:
                try:
                    # 使用 VLM 分析查询图像
                    description = await vlm_service.describe_image(img)
                    # 将图像描述加入查询
                    enhanced_query = f"{query}\n相关图像描述：{description}"
                    # 补充检索
                    additional_results = await self.text_retriever.retrieve(
                        query=enhanced_query,
                        knowledge_base_id=knowledge_base_id,
                        top_k=top_k // 2
                    )
                    result.text_results.extend(additional_results)
                except Exception as e:
                    logger.warning(f"Failed to analyze query image: {e}")
        
        # 3. 图像检索 (基于查询文本)
        if include_images:
            result.image_results = await self._search_images(
                query, knowledge_base_id, top_k
            )
        
        # 4. 音频/视频检索 (基于转写文本，由于存储在同一向量库中，已包含在文本检索中)
        # 这里可以根据 metadata 过滤特定类型
        
        # 5. 去重和排序
        result.text_results = self._deduplicate_results(result.text_results)[:top_k]
        
        return result
    
    async def _search_images(
        self,
        query: str,
        knowledge_base_id: Optional[int],
        top_k: int
    ) -> List[dict]:
        """
        搜索相关图像
        
        基于查询文本匹配图像描述
        """
        try:
            # 1. 对查询文本进行向量化
            query_embedding = embedding_service.embed_text(query)
            
            # 2. 从向量库中搜索图像
            image_results = vector_store.search_images(
                query_embedding=query_embedding,
                knowledge_base_id=knowledge_base_id,
                top_k=top_k
            )
            
            return image_results
            
        except Exception as e:
            logger.error(f"Image search failed: {e}")
            return []
    
    def _deduplicate_results(
        self,
        results: List[SearchResult]
    ) -> List[SearchResult]:
        """去重检索结果"""
        seen = set()
        unique = []
        for r in results:
            key = (r.document_id, r.chunk_index)
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique
    
    async def answer(
        self,
        query: str,
        images: Optional[List[bytes]] = None,
        knowledge_base_id: Optional[int] = None,
        top_k: int = 5,
    ) -> MultiModalResponse:
        """
        多模态问答
        
        Args:
            query: 问题文本
            images: 可选的参考图像
            knowledge_base_id: 知识库 ID
            top_k: 检索结果数
            
        Returns:
            MultiModalResponse 包含回答和来源
        """
        # 1. 多模态检索
        search_result = await self.retrieve(
            query=query,
            images=images,
            knowledge_base_id=knowledge_base_id,
            top_k=top_k
        )
        
        # 2. 构建上下文
        context_parts = []
        sources = []
        
        for r in search_result.text_results:
            context_parts.append(r.content)
            sources.append({
                "document_id": r.document_id,
                "chunk_index": r.chunk_index,
                "score": r.score,
                "content": r.content[:200] + "..." if len(r.content) > 200 else r.content
            })
        
        context = "\n\n---\n\n".join(context_parts)
        
        # 3. 如果有查询图像，用 VLM 生成回答
        if images:
            # 构建包含图像的 prompt
            prompt = f"""基于以下检索到的上下文信息，回答用户的问题。

上下文信息：
{context}

用户问题：{query}

请结合图像内容和上下文信息给出准确、详细的回答。"""
            
            response = await vlm_service.analyze_images(images, prompt)
            answer = response.content
            has_multimodal = True
        else:
            # 使用现有的 RAG 问答
            rag_response = await self.text_retriever.answer(
                query=query,
                knowledge_base_id=knowledge_base_id,
                top_k=top_k
            )
            answer = rag_response.answer
            has_multimodal = False
        
        return MultiModalResponse(
            answer=answer,
            sources=sources,
            images=search_result.image_results,
            has_multimodal_context=has_multimodal
        )
    
    async def answer_with_image(
        self,
        query: str,
        image: bytes,
        knowledge_base_id: Optional[int] = None,
    ) -> MultiModalResponse:
        """
        图文问答 (便捷方法)
        
        Args:
            query: 问题文本
            image: 参考图像
            knowledge_base_id: 知识库 ID
            
        Returns:
            MultiModalResponse
        """
        return await self.answer(
            query=query,
            images=[image],
            knowledge_base_id=knowledge_base_id
        )


# 单例
multimodal_retriever = MultiModalRetriever()
