"""查询重写服务 - Multi-Query Expansion"""

import logging
from typing import List
from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from ..config import settings

logger = logging.getLogger(__name__)


class QueryVariations(BaseModel):
    variations: List[str] = Field(description="List of 3 alternative search queries")


class QueryRewriter:
    """查询重写器"""
    
    def __init__(self):
        self.llm = ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=0.5, # 稍微增加创造性以生成不同角度的查询
            format="json",
        )
        self.parser = JsonOutputParser(pydantic_object=QueryVariations)
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个专业的搜索引擎优化专家。你的任务是根据用户的原始问题，生成 3 个不同角度的搜索查询词（Queries），以便在知识库中检索到相关文档。

要求：
1. **语义扩展**：使用同义词、近义词替换核心概念。
2. **问题拆解**：如果问题复杂，尝试拆分为更具体的子问题。
3. **关键信息提取**：生成仅包含核心关键词的查询。
4. **输出格式**：必须是合法的 JSON，包含一个 "variations" 列表。

示例：
用户问题："如何配置 Docker 的 GPU 支持？"
输出：
{{
    "variations": [
        "Docker GPU 配置教程 nvidia-container-toolkit",
        "docker-compose.yml 开启 GPU 资源限制",
        "Docker 无法识别 GPU 显卡 解决方案"
    ]
}}
"""),
            ("human", "{question}"),
        ])
        
        self.chain = self.prompt | self.llm | self.parser

    async def generate_multi_query(self, query: str) -> List[str]:
        """生成多路查询变体"""
        try:
            result = await self.chain.ainvoke({"question": query})
            variations = result.get("variations", [])
            
            # 过滤空字符串，确保去重
            clean_variations = list(set([v.strip() for v in variations if v.strip()]))
            
            # 总是包含原始查询
            if query not in clean_variations:
                clean_variations.insert(0, query)
                
            logger.info(f"Generated {len(clean_variations)} queries from '{query}': {clean_variations}")
            return clean_variations
            
        except Exception as e:
            logger.error(f"Query rewriting failed: {e}")
            return [query] # 降级：仅返回原始查询


# 单例
query_rewriter = QueryRewriter()
