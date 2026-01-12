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
