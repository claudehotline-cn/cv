
import logging
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase
from ..config import settings
from .llm_service import llm_service

logger = logging.getLogger(__name__)

class GraphRetriever:
    def __init__(self):
        self.driver = None
        self._init_driver()
        
    def _init_driver(self):
        try:
            self.driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
            )
            logger.info("Neo4j GraphRetriever connection initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Neo4j connection: {e}")

    async def retrieve(
        self,
        query: str,
        knowledge_base_id: Optional[int] = None,
        depth: int = 1
    ) -> List[Dict[str, Any]]:
        """图谱检索"""
        if not self.driver:
            self._init_driver()
            if not self.driver:
                return []

        # 1. 从Query中提取关键实体
        entities = await self._extract_entities_from_query(query)
        if not entities:
            logger.info("No entities found in query")
            return []
            
        logger.info(f"Entities extracted from query: {entities}")

        results = []
        seen_triples = set()

        for entity in entities:
            # 2. 精确匹配 + 邻居遍历 (不依赖全文索引)
            if knowledge_base_id is None:
                cypher = """
                MATCH (node:Entity)
                WHERE toLower(node.name) CONTAINS toLower($entity_name)
                MATCH (node)-[r:RELATION]-(neighbor:Entity)
                RETURN node.name as head, r.type as relation, neighbor.name as tail, neighbor.type as tail_type, r.source as source
                LIMIT 20
                """
                params = {"entity_name": entity}
            else:
                cypher = """
                MATCH (node:Entity)
                WHERE node.kb_id = $kb_id AND toLower(node.name) CONTAINS toLower($entity_name)
                MATCH (node)-[r:RELATION]-(neighbor:Entity)
                WHERE neighbor.kb_id = $kb_id
                RETURN node.name as head, r.type as relation, neighbor.name as tail, neighbor.type as tail_type, r.source as source
                LIMIT 20
                """
                params = {"entity_name": entity, "kb_id": int(knowledge_base_id)}
            
            try:
                with self.driver.session() as session:
                    result = session.run(cypher, params)
                    for record in result:
                        triple_str = f"{record['head']} - {record['relation']} -> {record['tail']}"
                        if triple_str not in seen_triples:
                            results.append({
                                "content": triple_str,
                                "metadata": {
                                    "source": record["source"],
                                    "type": "graph_relation",
                                    "head": record["head"],
                                    "tail": record["tail"],
                                    "relation": record["relation"]
                                },
                                "score": 1.0
                            })
                            seen_triples.add(triple_str)
                        
            except Exception as e:
                logger.error(f"Error querying Neo4j for entity {entity}: {e}")
                
        return results

    def _extract_entities_fallback(self, query: str) -> List[str]:
        """Fallback entity extraction without LLM (best-effort)."""
        import re

        q = (query or "").strip()
        if not q:
            return []

        # Remove common question words to avoid noisy entities.
        q2 = re.sub(r"[\s\t]+", " ", q)
        q2 = re.sub(r"(是什么|是什么\?|是什么\？|怎么|如何|为什么|多少|哪些|是否|能否|请问)", " ", q2)
        q2 = q2.strip()

        candidates: List[str] = []

        # Prefer full query if it's short.
        if 2 <= len(q2) <= 20:
            candidates.append(q2)

        # Chinese character sequences
        candidates.extend(re.findall(r"[\u4e00-\u9fff]{2,}", q2))
        # Alnum tokens
        candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,}", q2))
        # Dedup while preserving order
        out: List[str] = []
        seen = set()
        for c in candidates:
            c = c.strip()
            if not c:
                continue
            if c in seen:
                continue
            seen.add(c)
            out.append(c)

        return out[:5]

    async def _extract_entities_from_query(self, query: str) -> List[str]:
        """从用户问题中提取实体"""
        prompt = f"""
        请从以下问题中提取关键实体（人名、产品名、公司名、专业术语等）。
        只提取最重要的名词。

        问题：{query}

        输出格式：用逗号分隔的实体列表，不要解释。
        例如：埃隆·马斯克, 特斯拉, 火箭
        """
        try:
            response = await llm_service.generate(prompt)
            # 清理thinking标签
            if "<think>" in response:
                response = response.split("</think>")[-1]
            entities = [e.strip() for e in response.split(",") if e.strip()]
            if entities:
                return entities
        except Exception as e:
            logger.warning(f"LLM entity extraction failed, using fallback: {e}")

        return self._extract_entities_fallback(query)

graph_retriever = GraphRetriever()
