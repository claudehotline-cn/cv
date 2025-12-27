from typing import Any, Dict, List, Optional
import json
import logging
from langchain_core.messages import AIMessage, BaseMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from langgraph.types import Overwrite

_LOGGER = logging.getLogger(__name__)

class StructuredOutputToTextMiddleware(AgentMiddleware):
    """Middleware to ensure structured output is returned as text in the final message.
    
    This bridges the gap between DeepAgents' SubAgent (which returns messages[-1].text)
    and LangChain's structured output (which places result in structured_response or tool calls).
    """
    
    def after_agent(self, state: AgentState, runtime: Runtime[Any], result: Any = None) -> Dict[str, Any] | None:
        """After agent execution, check for structured response and copy to messages."""
        
        # 1. Check if structured_response exists (from response_format)
        if "structured_response" in state and state["structured_response"]:
            structured_data = state["structured_response"]
            _LOGGER.info("Middleware: Found structured_response, converting to text message.")
            
            # Serialize to JSON
            try:
                if hasattr(structured_data, "model_dump_json"):
                    json_str = structured_data.model_dump_json()
                else:
                    json_str = json.dumps(structured_data, default=str, ensure_ascii=False)
                
                # Add DATA_RESULT prefix for frontend detection
                content = f"DATA_RESULT:{json_str}"
                return {"messages": [AIMessage(content=content)]}
                
            except Exception as e:
                _LOGGER.error("Middleware: Failed to serialize structured_response: %s", e)
        
        # 2. Fallback: Check if any ToolMessage has DATA_RESULT/CHART_DATA but it wasn't returned as final output
        # This handles cases where SubAgent executed a tool (which returned DATA_RESULT)
        # but the SubAgent's final AIMessage only contained text (e.g. "Chart generated").
        if "messages" in state:
            messages = state["messages"]
            last_msg = messages[-1] if messages else None
            
            # Find the last tool output with structured data
            structured_tool_output = None
            for msg in reversed(messages):
                if hasattr(msg, "content") and isinstance(msg.content, str):
                    if "DATA_RESULT:" in msg.content or "CHART_DATA:" in msg.content:
                         structured_tool_output = msg.content
                         break
            
            # If found, and the last message content is DIFFERENT (i.e. Agent didn't repeat it),
            # append it as a new message so 'task' tool returns it.
            if structured_tool_output:
                # Check if last message already contains it (simple containment check)
                if last_msg and isinstance(last_msg.content, str) and structured_tool_output not in last_msg.content:
                     _LOGGER.info("Middleware: Found hidden structured tool output, bubbling up to final message.")
                     
                     # Log the EXACT content being sent to frontend
                     _LOGGER.info(f"FINAL_BUBBLE_UP_CONTENT_PREVIEW: {structured_tool_output[:500]}...") 
                     
                     # Merge with existing text so we don't lose the natural language summary!
                     combined_content = f"{last_msg.content}\n\n{structured_tool_output}"
                     
                     # Append the combined message. DeepAgents 'task' tool will pick this as the final result.
                     return {"messages": [AIMessage(content=combined_content)]}

        return None
