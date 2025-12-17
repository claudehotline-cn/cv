"""RAG检索服务"""

import logging
from typing import List, Optional
from dataclasses import dataclass

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from ..config import settings
from .embedder import embedding_service
from .vector_store import vector_store, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class RAGResponse:
    """RAG问答响应"""
    answer: str
    sources: List[dict]


class RAGRetriever:
    """RAG检索器"""
    
    def __init__(self):
        # 初始化LLM
        self.llm = ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=0.7,
        )
        
        # RAG提示模板
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个专业的智能知识库助手。请**结合**你的专业知识和提供的上下文信息，全面、准确地回答用户的问题。

要求:
1. **深度结合**：以提供的上下文信息为事实基础，利用你的专业知识（如数学公式、代码实现、原理解释）对内容进行补充和完善，使答案更加完整和易懂。
2. **准确性**：确保引用的上下文内容准确无误，补充的专业知识必须也是客观正确的。
3. **诚实**：如果问题与上下文完全无关，且无法仅凭专业知识给出有上下文关联的回答，请说明"根据现有资料无法回答该问题"。
4. **格式规范**：请使用 **Markdown** 格式优化排版，数学公式**必须**使用 LaTeX 格式（如 $E=mc^2$）。
5. **来源标注**：回答中请在相关陈述后标注引用来源，例如 [1], [2]。

上下文信息:
{context}"""),
            ("human", "{question}"),
        ])
        
        # 输出解析器
        self.output_parser = StrOutputParser()
        
        # 构建链
        self.chain = self.prompt | self.llm | self.output_parser
    
    def retrieve(
        self,
        query: str,
        knowledge_base_id: Optional[int] = None,
        top_k: int = 5,
    ) -> List[SearchResult]:
        """检索相关文档"""
        # 生成查询向量
        query_embedding = embedding_service.embed_text(query)
        
        # 向量搜索
        results = vector_store.search(
            query_embedding=query_embedding,
            knowledge_base_id=knowledge_base_id,
            top_k=top_k,
        )
        
        return results
    
    async def answer(
        self,
        query: str,
        knowledge_base_id: Optional[int] = None,
        top_k: int = 5,
        use_graph: bool = True,  # 默认启用图谱融合
    ) -> RAGResponse:
        """Hybrid RAG问答 - 融合向量检索和图谱检索"""
        import asyncio
        
        # 1. 并行执行向量检索和图谱检索
        vector_results = self.retrieve(
            query=query,
            knowledge_base_id=knowledge_base_id,
            top_k=top_k,
        )
        
        graph_results = []
        if use_graph:
            try:
                from .graph_retriever import graph_retriever
                graph_results = await graph_retriever.retrieve(
                    query=query,
                    knowledge_base_id=knowledge_base_id,
                    depth=2
                )
            except Exception as e:
                logger.warning(f"Graph retrieval failed, falling back to vector only: {e}")
        
        # 2. 融合结果构建上下文
        context_parts = []
        sources = []
        
        # 向量检索结果
        if vector_results:
            context_parts.append("### 文档片段:")
            for i, r in enumerate(vector_results):
                context_parts.append(f"[V{i+1}] {r.content}")
                sources.append({
                    "type": "vector",
                    "document_id": r.document_id,
                    "chunk_index": r.chunk_index,
                    "score": r.score,
                    "content_preview": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                })
        
        # 图谱检索结果
        if graph_results:
            context_parts.append("\n### 知识图谱关联:")
            for i, r in enumerate(graph_results):
                context_parts.append(f"[G{i+1}] {r['content']}")
                sources.append({
                    "type": "graph",
                    "document_id": 0,
                    "chunk_index": 0,
                    "score": r.get("score", 1.0),
                    "content_preview": r["content"],
                })
        
        if not context_parts:
            return RAGResponse(
                answer="未找到相关信息，无法回答该问题。",
                sources=[],
            )
        
        context = "\n\n".join(context_parts)
        
        # 3. 生成回答
        answer = await self.chain.ainvoke({
            "context": context,
            "question": query,
        })
        
        return RAGResponse(
            answer=answer,
            sources=sources,
        )


# 单例
rag_retriever = RAGRetriever()
