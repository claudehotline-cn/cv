import logging
import os
from typing import Any, Dict, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langgraph.runtime import Runtime

_LOGGER = logging.getLogger(__name__)

class ArticleContentMiddleware(AgentMiddleware):
    """Middleware to populate article_content from filesystem if missing.
    
    This helps avoid passing massive strings through the LLM context and ensures
    the frontend receives the full content even if the LLM truncates it.
    """
    
    def after_agent(self, state: AgentState, runtime: Runtime[Any], result: Any = None) -> Dict[str, Any] | None:
        """After agent execution, check/populate article_content."""
        
        # Check if we have a structured response
        if "structured_response" in state and state["structured_response"]:
            resp = state["structured_response"]
            
            # We are looking for ArticleAgentOutput (or compatible dict)
            # It should have 'md_path' and 'article_content' fields.
            
            md_path = None
            article_content = None
            
            # Handle Pydantic model
            if hasattr(resp, "md_path"):
                md_path = getattr(resp, "md_path", None)
                article_content = getattr(resp, "article_content", None)
            # Handle Dict
            elif isinstance(resp, dict):
                md_path = resp.get("md_path")
                article_content = resp.get("article_content")
            
            # If we have a path but incomplete content
            if md_path and (not article_content or len(article_content) < 1000):
                if os.path.exists(md_path):
                    try:
                        _LOGGER.info(f"Middleware: Reading full content from file: {md_path}")
                        with open(md_path, "r", encoding="utf-8") as f:
                            full_content = f.read()
                        
                        _LOGGER.info(f"Middleware: Read {len(full_content)} chars. Updating response.")
                        
                        # Update the response
                        if hasattr(resp, "model_copy"):
                            # Pydantic - use model_copy to return new instance
                            new_resp = resp.model_copy(update={"article_content": full_content})
                            return {"structured_response": new_resp}
                        elif isinstance(resp, dict):
                            # Dict - update in place (or copy)
                            resp["article_content"] = full_content
                            return {"structured_response": resp}
                            
                    except Exception as e:
                        _LOGGER.warning(f"Middleware: Failed to read file {md_path}: {e}")
                else:
                    _LOGGER.warning(f"Middleware: File not found at {md_path}")
        
        return None
