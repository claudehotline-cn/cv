from typing import Any, Dict
from agent_core.base import BaseAgent
from langchain_core.runnables import Runnable
from .graph import get_article_deep_agent_graph

class ArticleAgent(BaseAgent):
    """Article Generation Agent Plugin"""
    
    def get_graph(self) -> Runnable:
        return get_article_deep_agent_graph()

    def get_config(self) -> Dict[str, Any]:
        return {
            "name": "Article Agent",
            "key": "article_agent",
            "description": "Multi-agent article generation system with planning, research, writing, and assembly capabilities."
        }
