
import logging
from typing import Optional
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage
from ..config import settings

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self):
        self._llm = None
        
    @property
    def llm(self):
        """懒加载LLM实例"""
        if not self._llm:
            self._llm = ChatOllama(
                model=settings.llm_model,
                base_url=settings.ollama_base_url,
                temperature=0.1, # 抽取任务需要低随机性
            )
        return self._llm

    async def generate(self, prompt: str) -> str:
        """生成回答"""
        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            raise

llm_service = LLMService()
