import logging
from typing import Any, List, Dict, Union
from langchain_core.messages import BaseMessage

_LOGGER = logging.getLogger(__name__)

def extract_text_from_message(message: Union[BaseMessage, str, List, Dict]) -> str:
    """Robustly extract text content from a message object using content_blocks.
    
    Uses LangChain's .content_blocks attribute which provides standardized
    content representation regardless of whether the original content was
    a string or a list of blocks.
    
    Handles:
    1. str: Returns as-is.
    2. BaseMessage: Uses .content_blocks (always returns List[Dict]).
    3. List[Dict]: Iterates and joins 'text' fields.
    """
    if isinstance(message, str):
        return message
    
    # For BaseMessage, use content_blocks for standardized access
    if isinstance(message, BaseMessage):
        # content_blocks always returns a list, even for string content
        blocks = getattr(message, 'content_blocks', None)
        if blocks is not None:
            text_parts = []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        text_parts.append(text)
            return "\n".join(text_parts) if text_parts else ""
        # Fallback for older langchain versions without content_blocks
        content = message.content
        if isinstance(content, str):
            return content
    
    # Handle raw list/dict (Content Blocks passed directly)
    content = message
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    text_parts.append(text)
        return "\n".join(text_parts)
        
    return str(content)


def stream_reasoning(response, event_type: str = "reasoning") -> None:
    """Extract reasoning/CoT from LLM response and stream it directly to frontend.
    
    Uses get_stream_writer() to send custom events without storing in state.
    Expects reasoning to be in standard content_blocks with type="reasoning".
    
    Args:
        response: AIMessage from LLM
        event_type: Type label for the custom event (e.g., 'sql_reasoning', 'python_reasoning')
    """
    content_blocks = getattr(response, 'content_blocks', [])
    
    try:
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
        if not writer:
            _LOGGER.debug("[stream_reasoning] No writer available")
            return
            
        # Extract reasoning from standard content_blocks (type=reasoning)
        reasoning = ""
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "reasoning":
                reasoning = block.get("reasoning", "")
                break
        
        # Fallback: Check additional_kwargs (for streaming chunks or older LangChain versions)
        if not reasoning and hasattr(response, "additional_kwargs"):
            reasoning = response.additional_kwargs.get("reasoning_content") or \
                       response.additional_kwargs.get("reasoning")
        
        if reasoning:
            # Use 'reasoning' field to match standard block structure, regardless of event_type
            writer({"type": event_type, "reasoning": reasoning})
            _LOGGER.info("[stream_reasoning] Sent %s via custom stream (%d chars)", event_type, len(reasoning))
        else:
            _LOGGER.debug("[stream_reasoning] No reasoning content found in content_blocks or kwargs")
    except Exception as e:
        _LOGGER.debug("[stream_reasoning] get_stream_writer not available: %s", e)
