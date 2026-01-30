
import json
import logging
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase
from langchain_core.documents import Document
from ..config import settings
from .llm_service import llm_service

logger = logging.getLogger(__name__)

class GraphBuilder:
    def __init__(self):
        self.driver = None
        self._init_driver()
        
    def _init_driver(self):
        """初始化Neo4j连接"""
        try:
            self.driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
            )
            # 测试连接并创建约束
            # 注意：当前使用 namespaced id (kb_id:name) 来满足全局唯一约束。
            with self.driver.session() as session:
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE")
            logger.info("Neo4j connection initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Neo4j connection: {e}")

    async def build_from_documents(self, documents: List[Document]):
        """从文档列表构建图谱"""
        if not self.driver:
            self._init_driver()
            if not self.driver:
                logger.error("Neo4j not initialized, skipping graph build")
                return

        for doc in documents:
            try:
                # 1. 抽取实体和关系
                graph_data = await self._extract_graph_data(doc.page_content)
                
                # 2. 写入Neo4j
                if graph_data:
                    self._save_to_neo4j(graph_data, doc.metadata)
                    
            except Exception as e:
                logger.error(f"Error building graph for document {doc.metadata.get('source', 'unknown')}: {e}")

    async def _extract_graph_data(self, text: str) -> Optional[List[Dict[str, Any]]]:
        """使用LLM抽取实体和关系"""
        import re
        
        prompt = f"""你是一个专业的知识图谱构建专家。请从以下文本中提取实体和关系。

要求：
1. 提取重要实体（人名、地名、组织、概念、产品等）
2. 提取实体之间的关系
3. 输出必须是JSON数组格式，每个元素包含：head, head_type, tail, tail_type, relation
4. 只输出JSON数组，不要任何其他文字

示例输出：
[{{"head": "Tesla", "head_type": "Organization", "tail": "Elon Musk", "tail_type": "Person", "relation": "founded_by"}}]

文本：
{text[:1500]}

JSON:"""
        
        try:
            response = await llm_service.generate(
                prompt,
                model=settings.graph_llm_model,
                timeout_sec=settings.graph_llm_timeout_sec,
            )
            
            # 清理response
            json_str = response.strip()
            
            # 移除thinking标签
            if "<think>" in json_str:
                json_str = json_str.split("</think>")[-1].strip()
            
            # 辅助函数：提取最外层的JSON数组
            def extract_json_array(s):
                start = s.find('[')
                if start == -1:
                    return None
                
                count = 0
                for i in range(start, len(s)):
                    if s[i] == '[':
                        count += 1
                    elif s[i] == ']':
                        count -= 1
                        if count == 0:
                            return s[start:i+1]
                return None

            # 尝试多种提取方式
            extracted = None
            
            # 1. 尝试从代码块提取
            match = re.search(r'```(?:json)?\s*(.*?)\s*```', json_str, re.DOTALL)
            if match:
                extracted = extract_json_array(match.group(1))
                if not extracted: # 代码块里可能没有 []
                     extracted = match.group(1)
            
            # 2. 如果代码块没找到或无效，直接从全文提取
            if not extracted:
                 extracted = extract_json_array(json_str)

            if extracted:
                 return json.loads(extracted)
            
            logger.warning(f"Could not find JSON in response: {json_str[:200]}...")
            return None
            
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error: {e}, response: {json_str[:200] if 'json_str' in dir() else 'N/A'}...")
            return None
        except Exception as e:
            logger.error(f"Error extracting graph data: {e}")
            return None

    def _save_to_neo4j(self, graph_data: List[Dict[str, Any]], metadata: Dict[str, Any]):
        """保存三元组到Neo4j"""
        if not graph_data:
            return

        # 必需字段
        required_fields = ["head", "head_type", "tail", "tail_type", "relation"]

        for item in graph_data:
            try:
                # 验证必需字段
                if not isinstance(item, dict):
                    logger.warning(f"Skipping non-dict item: {item}")
                    continue
                
                missing_fields = [f for f in required_fields if f not in item or not item[f]]
                if missing_fields:
                    logger.warning(f"Skipping triple with missing fields {missing_fields}: {item}")
                    continue
                
                cypher = """
                MERGE (h:Entity {id: $head_id})
                ON CREATE SET h.name = $head_name, h.type = $head_type, h.kb_id = $kb_id
                
                MERGE (t:Entity {id: $tail_id})
                ON CREATE SET t.name = $tail_name, t.type = $tail_type, t.kb_id = $kb_id
                
                MERGE (h)-[r:RELATION {type: $relation, kb_id: $kb_id}]->(t)
                SET r.source = $source
                """
                
                kb_id = metadata.get("kb_id")
                kb_id_int = int(kb_id) if kb_id is not None else 0

                head_name = str(item["head"]).strip()
                tail_name = str(item["tail"]).strip()
                params = {
                    "kb_id": kb_id_int,
                    "head_id": f"{kb_id_int}:{head_name}",
                    "head_name": head_name,
                    "head_type": str(item.get("head_type", "Unknown")).strip(),
                    "tail_id": f"{kb_id_int}:{tail_name}",
                    "tail_name": tail_name,
                    "tail_type": str(item.get("tail_type", "Unknown")).strip(),
                    "relation": str(item["relation"]).upper().replace(" ", "_").strip(),
                    "source": metadata.get("source", "unknown"),
                }
                
                with self.driver.session() as session:
                    session.run(cypher, params)
                
            except Exception as e:
                logger.error(f"Error saving triple to Neo4j: {e}, item: {item}")

graph_builder = GraphBuilder()
