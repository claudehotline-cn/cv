from typing import Any, Dict
from agent_core.base import BaseAgent
from langchain_core.runnables import Runnable
from .graph import get_data_deep_agent_graph

class DataAgent(BaseAgent):
    """Deep Data Analysis Agent Plugin"""
    
    def get_graph(self) -> Runnable:
        return get_data_deep_agent_graph()

    def get_config(self) -> Dict[str, Any]:
        return {
            "name": "Data Agent",
            "key": "data_agent",
            "description": "Powerful data analysis agent with SQL, Python, and Visualization capabilities."
        }
