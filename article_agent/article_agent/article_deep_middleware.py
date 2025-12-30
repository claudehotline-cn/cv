import logging
import json
from typing import Any, Dict, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

_LOGGER = logging.getLogger(__name__)

class ArticleContentMiddleware(AgentMiddleware):
    """Middleware to bubbling up article_content from Assembler to Main Agent output.
    
    It scans the message history for the Assembler's output (which now includes article_content)
    and populates the final response with it.
    """
    
    def after_agent(self, state: AgentState, runtime: Runtime[Any], result: Any = None) -> Dict[str, Any] | None:
        """After agent execution, populate article_content from message history."""
        
        # Check if we have a structured response (ArticleAgentOutput)
        if "structured_response" in state and state["structured_response"]:
            resp = state["structured_response"]
            
            # Check if article_content is missing
            current_content = None
            if hasattr(resp, "article_content"):
                current_content = getattr(resp, "article_content", None)
            elif isinstance(resp, dict):
                current_content = resp.get("article_content")
            
            # Only proceed if content is missing or too short
            if not current_content or len(current_content) < 100:
                _LOGGER.info("Middleware: article_content missing in final response, scanning history...")
                
                # Scan messages for Assembler's output
                # We look for a message from 'assembler_agent' or containing 'article_content' in tool output
                messages = state.get("messages", [])
                found_content = None
                
                for msg in reversed(messages):
                    # Check structured tool output in content (DeepAgents bubbles up sub-agent result)
                    if isinstance(msg, AIMessage) and msg.content:
                        content_str = str(msg.content)
                        # Check if it looks like JSON and has article_content
                        # DeepAgents SubAgents return JSON string in content often
                        if "article_content" in content_str and len(content_str) > 1000:
                             try:
                                # Try to parse json if it looks like one
                                # Or regex extract it? JSON parsing is safer but might be partial text
                                # Let's try to see if we can find the `article_content` field
                                start_idx = content_str.find('"article_content"')
                                if start_idx != -1:
                                    # Very naive extraction if JSON is complex, but let's try strict JSON first
                                    # Often the content is "DATA_RESULT:..." or just raw JSON
                                    clean_json = content_str.strip()
                                    if clean_json.startswith("DATA_RESULT:"):
                                        clean_json = clean_json[12:]
                                    
                                    data = json.loads(clean_json)
                                    if "article_content" in data and data["article_content"]:
                                        found_content = data["article_content"]
                                        _LOGGER.info(f"Middleware: Found content in message history (length={len(found_content)})")
                                        break
                             except:
                                 pass
                
                if found_content:
                    # Update response
                    if hasattr(resp, "model_copy"):
                        new_resp = resp.model_copy(update={"article_content": found_content})
                        return {"structured_response": new_resp}
                    elif isinstance(resp, dict):
                        resp["article_content"] = found_content
                        return {"structured_response": resp}
        
        return None
