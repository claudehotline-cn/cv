
import logging
from typing import List, Tuple
from sentence_transformers import CrossEncoder
from ..config import settings
import torch

logger = logging.getLogger(__name__)

class Reranker:
    def __init__(self):
        # 使用轻量级重排序模型，适合CPU环境
        # 也可以配置更强的 'BAAI/bge-reranker-base'
        self.model_name = settings.reranker_model
        self.model = None
        self._init_model()

    def _init_model(self):
        try:
            logger.info(f"Loading reranker model: {self.model_name}")
            self.model = CrossEncoder(self.model_name, default_activation_function=torch.nn.Sigmoid())
            logger.info("Reranker model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load reranker model: {e}")

    def rerank(self, query: str, documents: List[str], top_k: int = 5) -> List[Tuple[int, float]]:
        """
        对文档进行重排序
        :param query: 查询语句
        :param documents: 候选文档列表
        :param top_k: 返回前k个
        :return: List[(original_index, score)]
        """
        if not self.model or not documents:
            return [(i, 0.0) for i in range(min(len(documents), top_k))]
        
        try:
            pairs = [[query, doc] for doc in documents]
            scores = self.model.predict(pairs)
            
            # 组合 (index, score)
            results = list(enumerate(scores))
            
            # 按分数降序排序
            results.sort(key=lambda x: x[1], reverse=True)
            
            return results[:top_k]
            
        except Exception as e:
            logger.error(f"Error during reranking: {e}")
            # 出错时降级为不排序，直接返回前k个
            return [(i, 0.0) for i in range(min(len(documents), top_k))]

# 单例
reranker = Reranker()
