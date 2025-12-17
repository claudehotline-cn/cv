
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
            cypher = """
            MATCH (node:Entity)
            WHERE toLower(node.id) CONTAINS toLower($entity_name)
            MATCH (node)-[r]-(neighbor)
            RETURN node.id as head, type(r) as relation, neighbor.id as tail, neighbor.type as tail_type, r.source as source
            LIMIT 20
            """
            
            try:
                with self.driver.session() as session:
                    result = session.run(cypher, {"entity_name": entity})
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
            return entities
        except Exception as e:
            logger.error(f"Error extracting entities: {e}")
            return []

graph_retriever = GraphRetriever()
