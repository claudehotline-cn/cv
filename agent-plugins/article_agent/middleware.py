from typing import Any, Dict
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langgraph.runtime import Runtime
import logging

_LOGGER = logging.getLogger(__name__)

class TaskContextMiddleware(AgentMiddleware):
    """
    Middleware to sync task_id from Runtime config to local ContextVar.
    This ensures that artifacts.py (using get_article_dir) generates paths 
    consistent with the current Task ID.
    """
    
    def before_agent(self, state: AgentState, runtime: Runtime[Any]) -> Dict[str, Any] | None:
        try:
            task_id = runtime.config.get("configurable", {}).get("task_id", "main")
            from .config import set_current_task_id
            
            _LOGGER.info(f"[TaskContextMiddleware] Setting Task ID context to: {task_id}")
            set_current_task_id(task_id)
        except Exception as e:
            _LOGGER.warning(f"[TaskContextMiddleware] Failed to set task ID context: {e}")
            
        return None
