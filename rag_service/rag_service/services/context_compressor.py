"""上下文压缩服务 - 从检索结果中提取与查询最相关的内容"""

import logging
from typing import List, Optional
from langchain_ollama import ChatOllama
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ..config import settings

logger = logging.getLogger(__name__)

# 压缩提示词
COMPRESSION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是一个专业的信息提取助手。你的任务是从给定的文档片段中提取与用户问题最相关的内容。

规则：
1. 只保留与问题直接相关的句子或段落
2. 保持原文措辞，不要改写或总结
3. 如果整个片段都不相关，返回 "[无相关内容]"
4. 如果整个片段都相关，可以返回完整内容
5. 用 "..." 连接不连续的相关片段
6. 目标是将内容压缩到原来的 30-50%，同时保留所有关键信息"""),
    ("human", """用户问题：{query}

文档片段：
{content}

请提取与问题相关的内容：""")
])


class ContextCompressor:
    """使用 LLM 压缩检索上下文"""
    
    def __init__(self):
        self.llm = ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=0,  # 确定性输出
        )
        self.chain = COMPRESSION_PROMPT | self.llm | StrOutputParser()
    
    async def compress(self, query: str, content: str, max_length: int = 1500) -> str:
        """
        压缩单个文档内容
        
        Args:
            query: 用户查询
            content: 原始文档内容
            max_length: 如果原文短于此长度，不进行压缩
            
        Returns:
            压缩后的内容
        """
        # 短内容不需要压缩
        if len(content) <= max_length:
            return content
        
        try:
            compressed = await self.chain.ainvoke({
                "query": query,
                "content": content
            })
            
            # 检查压缩结果
            if "[无相关内容]" in compressed or len(compressed.strip()) < 50:
                logger.warning(f"Compression returned no relevant content, using original")
                return content
            
            compression_ratio = len(compressed) / len(content)
            logger.info(f"Compressed content: {len(content)} -> {len(compressed)} chars ({compression_ratio:.1%})")
            
            return compressed.strip()
            
        except Exception as e:
            logger.error(f"Context compression failed: {e}")
            return content  # 失败时返回原文
    
    async def compress_results(
        self, 
        query: str, 
        contents: List[str],
        max_length: int = 1500
    ) -> List[str]:
        """
        批量压缩多个检索结果
        
        Args:
            query: 用户查询
            contents: 原始内容列表
            max_length: 触发压缩的最小长度
            
        Returns:
            压缩后的内容列表
        """
        compressed_list = []
        
        for content in contents:
            compressed = await self.compress(query, content, max_length)
            compressed_list.append(compressed)
        
        return compressed_list


# 单例
context_compressor = ContextCompressor()
