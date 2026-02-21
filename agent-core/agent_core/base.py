from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from langchain_core.runnables import Runnable

class BaseAgent(ABC):
    """Abstract base class for all Agents in the platform."""
    
    @abstractmethod
    def get_graph(self) -> Runnable:
        """Return the compiled LangGraph workflow runnable.
        
        The runnable should accept a State dict and return a State dict (or stream events).
        """
        pass

    @abstractmethod
    def get_config(self) -> Dict[str, Any]:
        """Return agent configuration schema or defaults."""
        return {}
