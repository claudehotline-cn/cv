"""RAG检索服务"""

import logging
from typing import List, Optional
from dataclasses import dataclass

from ..config import settings
from .embedder import embedding_service
from .vector_store import vector_store, SearchResult
from .llm_service import llm_service

logger = logging.getLogger(__name__)


@dataclass
class RAGResponse:
    """RAG问答响应"""
    answer: str
    sources: List[dict]


class RAGRetriever:
    """RAG检索器"""
    
    def __init__(self):
        pass
    
    
    
    async def retrieve(
        self,
        query: str,
        knowledge_base_id: Optional[int] = None,
        top_k: int = 5,
        enable_query_expansion: bool = True,
        expand_to_parent: bool = True,  # 是否扩展到父块内容
        compress_context: Optional[bool] = None,  # 是否压缩上下文，默认读取配置
    ) -> List[SearchResult]:
        """
        混合检索 (Vector + Keyword) + Multi-Query Expansion + Reranking + Parent Expansion + Context Compression
        """
        from ..config import settings
        
        # 如果未指定，使用配置文件默认值
        if compress_context is None:
            compress_context = settings.enable_context_compression
        
        # 1. 查询重写/扩展
        queries = [query]
        if enable_query_expansion:
            try:
                from .query_rewriter import query_rewriter
                # 并行获取扩展查询
                queries = await query_rewriter.generate_multi_query(query)
            except Exception as e:
                logger.warning(f"Query expansion failed: {e}")
        
        # 2. 多路召回 (Parallel Execution for all queries)
        all_vector_results = []
        all_keyword_results = []
        
        initial_k = top_k * 2
        
        for q in queries:
            q_emb = embedding_service.embed_text(q)
            v_res = vector_store.search(q_emb, knowledge_base_id, top_k=initial_k)
            all_vector_results.extend(v_res)
            
            k_res = vector_store.search_keyword(q, knowledge_base_id, top_k=initial_k)
            all_keyword_results.extend(k_res)
            
        # 3. 混合融合 (Global RRF)
        fused_candidates = self._hybrid_fuse(all_vector_results, all_keyword_results, top_k=top_k * 4)
        
        if not fused_candidates:
            return []
            
        # 4. 重排序 (Rerank)
        try:
            from .reranker import reranker
            
            candidate_texts = [c.content for c in fused_candidates]
            ranked_results = reranker.rerank(query, candidate_texts, top_k=top_k)
            
            final_results = []
            for idx, score in ranked_results:
                candidate = fused_candidates[idx]
                candidate.score = float(score)
                final_results.append(candidate)
                
        except Exception as e:
            logger.error(f"Reranking failed, falling back to fused results: {e}")
            final_results = fused_candidates[:top_k]
        
        # final_results = fused_candidates[:top_k]

        # 5. 父块内容扩展 (Parent-Child Indexing)
        if expand_to_parent and final_results:
            final_results = self._expand_to_parent_content(final_results)
        
        # 6. 上下文压缩 (Context Compression)
        if compress_context and final_results:
            final_results = await self._compress_contexts(query, final_results)
            
        logger.info(f"Retrieve: {len(queries)} queries -> {len(all_vector_results)+len(all_keyword_results)} raw -> {len(final_results)} final")
        return final_results

    async def _compress_contexts(self, query: str, results: List[SearchResult]) -> List[SearchResult]:
        """压缩检索结果的上下文内容"""
        try:
            from .context_compressor import context_compressor
            
            contents = [r.content for r in results]
            compressed = await context_compressor.compress_results(query, contents)
            
            for r, c in zip(results, compressed):
                if c != r.content:
                    r.metadata["original_length"] = len(r.content)
                    r.metadata["compressed_length"] = len(c)
                    r.content = c
            
            return results
        except Exception as e:
            logger.error(f"Context compression failed: {e}")
            return results  # 失败时返回原结果

    def _expand_to_parent_content(self, results: List[SearchResult]) -> List[SearchResult]:
        """
        将子块扩展为父块内容 (去重)
        
        如果多个子块指向同一个父块，只保留得分最高的那个
        """
        # 收集需要查询的 parent_ids
        parent_ids = set(r.parent_id for r in results if r.parent_id is not None)
        
        if not parent_ids:
            return results  # 没有父块，直接返回
        
        # 批量获取父块内容
        parent_contents = vector_store.get_parents_by_ids(list(parent_ids))
        
        # 扩展内容并去重
        seen_parents = set()
        expanded_results = []
        
        for r in results:
            if r.parent_id is not None:
                # 这是一个子块
                if r.parent_id in seen_parents:
                    continue  # 同一个父块已经出现过，跳过
                seen_parents.add(r.parent_id)
                
                # 替换为父块内容
                parent_content = parent_contents.get(r.parent_id)
                if parent_content:
                    r.content = parent_content
                    r.metadata["expanded_from_child"] = True
            
            expanded_results.append(r)
        
        logger.info(f"Parent expansion: {len(results)} -> {len(expanded_results)} (deduped by parent)")
        return expanded_results

    def _hybrid_fuse(self, vector_results: List[SearchResult], keyword_results: List[SearchResult], top_k: int, k_const: int = 60) -> List[SearchResult]:
        """Reciprocal Rank Fusion (RRF)"""
        # Map: (doc_id, chunk_index) -> Score
        fused_scores = {}
        # Map: (doc_id, chunk_index) -> Candidate Object
        candidates_map = {}
        
        # Process Vector Results
        for rank, res in enumerate(vector_results):
            key = (res.document_id, res.chunk_index)
            candidates_map[key] = res
            fused_scores[key] = fused_scores.get(key, 0.0) + (1.0 / (k_const + rank + 1))
            
        # Process Keyword Results
        for rank, res in enumerate(keyword_results):
            key = (res.document_id, res.chunk_index)
            if key not in candidates_map:
                candidates_map[key] = res
            fused_scores[key] = fused_scores.get(key, 0.0) + (1.0 / (k_const + rank + 1))
            
        # Sort by Fused Score DESC
        sorted_keys = sorted(fused_scores.keys(), key=lambda k: fused_scores[k], reverse=True)
        
        # Return Top K
        return [candidates_map[k] for k in sorted_keys[:top_k]]
    
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
        vector_results = await self.retrieve(
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

        system_prompt = f"""你是一个专业的智能知识库助手。请**结合**你的专业知识和提供的上下文信息，全面、准确地回答用户的问题。

要求:
1. **深度结合**：以提供的上下文信息为事实基础，利用你的专业知识（如数学公式、代码实现、原理解释）对内容进行补充和完善，使答案更加完整和易懂。
2. **准确性**：确保引用的上下文内容准确无误，补充的专业知识必须也是客观正确的。
3. **诚实**：如果问题与上下文完全无关，且无法仅凭专业知识给出有上下文关联的回答，请说明"根据现有资料无法回答该问题"。
4. **格式规范**：请使用 **Markdown** 格式优化排版，数学公式**必须**使用 LaTeX 格式（如 $E=mc^2$）。
5. **来源标注**：回答中请在相关陈述后标注引用来源，例如 [1], [2]。

上下文信息:
{context}"""

        # 3. 生成回答（vLLM）
        answer = await llm_service.generate(
            query,
            model=settings.llm_model,
            timeout_sec=settings.llm_timeout_sec,
            temperature=0.7,
            system_prompt=system_prompt,
        )
        
        return RAGResponse(
            answer=answer,
            sources=sources,
        )


# 单例
rag_retriever = RAGRetriever()
