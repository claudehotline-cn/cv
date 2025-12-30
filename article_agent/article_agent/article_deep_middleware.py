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
            
            # Debug log for frontend response
            try:
                if hasattr(resp, "model_dump"):
                    debug_dict = resp.model_dump()
                elif hasattr(resp, "dict"):
                    debug_dict = resp.dict()
                else: 
                    debug_dict = resp if isinstance(resp, dict) else str(resp)
                
                # Truncate long content for log readability but show length
                log_copy = debug_dict.copy() if isinstance(debug_dict, dict) else {}
                content_len = len(log_copy.get("article_content") or "")
                log_copy["article_content"] = f"<CONTENT_LENGTH_{content_len}>"
                _LOGGER.info(f"Middleware: Final structured_response passed to frontend: {json.dumps(log_copy, default=str)}")
            except Exception as e:
                _LOGGER.error(f"Middleware: Failed to log response: {e}")

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
                    
                    # Log first 200 chars to identify content format
                    if "article_content" in content_str:
                        _LOGGER.info(f"Msg[-{i+1}] ({msg_type}) contains 'article_content'. Preview: {content_str[:200]}...")
                    
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
        
        # Fallback: If structured_response is missing but we have a final message with content
        elif result and hasattr(result, "content") and len(str(result.content)) > 100:
             _LOGGER.warning("Middleware: Structured response MISSING. Fallback: Wrapping raw message content.")
             # Construct a fallback dictionary matching ArticleAgentOutput
             fallback_resp = {
                 "status": "success",
                 "title": "Generated Article",
                 "md_path": "",
                 "md_url": "",
                 "summary": "Generated from raw output.",
                 "word_count": len(str(result.content)),
                 "article_content": str(result.content),
                 "error_message": None
             }
             _LOGGER.info(f"Middleware: Created fallback structured_response with {len(str(result.content))} chars.")
             return {"structured_response": fallback_resp}

        return None

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
            
        # 2. Try ast.literal_eval (Handles Python dict string representation: {'key': 'value'})
        try:
            import ast
            # Only attempt if it looks like a dict
            if text.strip().startswith("{") and "article_content" in text:
                data = ast.literal_eval(text)
                if isinstance(data, dict) and data.get("article_content"):
                    return data["article_content"]
        except:
            pass
            
        # 3. Try clean prefix JSON (e.g. DATA_RESULT:...)
        if "DATA_RESULT:" in text:
            try:
                clean = text.split("DATA_RESULT:", 1)[1].strip()
                data = json.loads(clean)
                if isinstance(data, dict) and data.get("article_content"):
                    return data["article_content"]
            except:
                pass

        # 4. Try Regex for key='value' or key="value" format (Common in some LLM text outputs)
        # Matches: article_content='...' or article_content="..."
        # Note: This is a basic regex and might fail on complex nested quotes, but handles simple cases.
        try:
            # Match article_content='...' single usage
            patterns = [
                r"article_content='((?:[^'\\]|\\.)*)'",  # Single qoutes
                r'article_content="((?:[^"\\]|\\.)*)"',  # Double quotes
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    return match.group(1)
        except Exception as e:
            _LOGGER.debug(f"Middleware: Regex extraction failed: {e}")

        # 5. Try "Header: Content" format (Common in Assembler natural language output)
        # Matches text after "- 文章内容:" or "文章内容:"
        markers = ["- 文章内容:", "文章内容:"]
        for marker in markers:
            if marker in text:
                try:
                    # Extract everything after marker
                    parts = text.split(marker, 1)
                    if len(parts) > 1:
                        candidate = parts[1].strip()
                        # Clean up known trailing phrases from prompt
                        if "任务圆满结束" in candidate:
                            candidate = candidate.split("任务圆满结束")[0].strip()
                        if len(candidate) > 100: # Simple validation to ensure it's actual content
                             return candidate
                except:
                    pass

        return None
