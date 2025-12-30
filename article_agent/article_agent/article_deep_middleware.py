import logging
import json
import re
from typing import Any, Dict, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langchain_core.messages import AIMessage, ToolMessage, BaseMessage
from langgraph.runtime import Runtime

_LOGGER = logging.getLogger(__name__)

class ArticleContentMiddleware(AgentMiddleware):
    """Middleware to bubbling up article_content from Assembler to Main Agent output (In-Memory)."""
    
    def after_agent(self, state: AgentState, runtime: Runtime[Any], result: Any = None) -> Dict[str, Any] | None:
        """After agent execution, populate article_content from message history."""
        
        # Check if we have a structured response (ArticleAgentOutput)
        if "structured_response" in state and state["structured_response"]:
            resp = state["structured_response"]
            
            # Check current content
            current_content = None
            if hasattr(resp, "article_content"):
                current_content = getattr(resp, "article_content", None)
            elif isinstance(resp, dict):
                current_content = resp.get("article_content")
            
            # Only proceed if content is missing
            if not current_content or len(current_content) < 100:
                _LOGGER.info("Middleware: article_content missing in final response. Scanning history...")
                
                messages = state.get("messages", [])
                found_content = None
                
                # Debug: log message types
                _LOGGER.info(f"Middleware: Scanning {len(messages)} messages.")
                
                for i, msg in enumerate(reversed(messages)):
                    content_str = str(msg.content)
                    msg_type = type(msg).__name__
                    
                    # _LOGGER.info(f"Msg[-{i+1}] ({msg_type}): {content_str[:100]}...")
                    
                    # 1. 尝试直接从 ToolMessage 中提取 (DeepAgents 可能会把 SubAgent 结果作为 Tool Message)
                    if isinstance(msg, ToolMessage) or (msg_type == "ToolMessage"):
                        # 检查是否包含 article_content
                        if "article_content" in content_str:
                             extracted = self._extract_content(content_str)
                             if extracted:
                                 found_content = extracted
                                 _LOGGER.info(f"Middleware: Found content in ToolMessage[-{i+1}]")
                                 break

                    # 2. 尝试从 AIMessage 中提取 (SubAgent 的输出可能被包装在 AIMessage 中)
                    if isinstance(msg, AIMessage) or (msg_type == "AIMessage"):
                        if "article_content" in content_str:
                             extracted = self._extract_content(content_str)
                             if extracted:
                                 found_content = extracted
                                 _LOGGER.info(f"Middleware: Found content in AIMessage[-{i+1}]")
                                 break
                
                if found_content:
                    _LOGGER.info(f"Middleware: Successfully extracted content ({len(found_content)} chars). Updating response.")
                    # Update response
                    if hasattr(resp, "model_copy"):
                        new_resp = resp.model_copy(update={"article_content": found_content})
                        return {"structured_response": new_resp}
                    elif isinstance(resp, dict):
                        resp["article_content"] = found_content
                        return {"structured_response": resp}
                else:
                    _LOGGER.warning("Middleware: Failed to find article_content in ANY message history.")
        
        return None

    def _extract_content(self, text: str) -> Optional[str]:
        """Helper to extract article_content from a string (JSON or partial JSON)."""
        if not text: return None
        
        # 1. Try strict JSON
        try:
            data = json.loads(text)
            if isinstance(data, dict) and data.get("article_content"):
                return data["article_content"]
        except:
            pass
            
        # 2. Try clean prefix JSON (e.g. DATA_RESULT:...)
        if "DATA_RESULT:" in text:
            try:
                clean = text.split("DATA_RESULT:", 1)[1].strip()
                data = json.loads(clean)
                if isinstance(data, dict) and data.get("article_content"):
                    return data["article_content"]
            except:
                pass

        # 3. Try Regex (fallback for dirty strings)
        # 查找 "article_content": "..." 模式
        # 注意：Markdown 内容可能包含转义字符，regex 提取比较危险，但可以尝试
        try:
            # 匹配 "article_content": " (capturing group) ", 
            # 这是一个非贪婪匹配，可能无法匹配包含转义引号的内容
            # 更好的方式是寻找 key 的位置，然后尝试解析后续的 value
            pass 
        except:
            pass
            
        return None
