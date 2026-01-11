import logging
from typing import Any, List, Dict, Union
from langchain_core.messages import BaseMessage

_LOGGER = logging.getLogger(__name__)

def extract_text_from_message(message: Union[BaseMessage, str, List, Dict]) -> str:
    """Robustly extract text content from a message object, string, or content block list.
    
    Handles:
    1. str: Returns as-is.
    2. BaseMessage: Inspects .content (str or list).
    3. List[Dict]: Iterates and joins 'text' fields.
    """
    if isinstance(message, str):
        return message
        
    content = message
    if isinstance(message, BaseMessage):
        content = message.content
        
    if isinstance(content, str):
        return content
    
    if isinstance(content, list):
        # Handle Content Blocks
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    text_parts.append(text)
        return "\n".join(text_parts)
        
    return str(content)
