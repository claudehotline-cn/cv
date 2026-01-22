"""Article Agent Utils - Text Extraction Helpers"""
from __future__ import annotations

from typing import Any


def extract_text_content(message: Any) -> str:
    """Extract clean text content from AIMessage, ignoring thinking/reasoning blocks.
    
    Handles multiple content formats:
    - String content
    - List of content blocks (dict with type/text)
    - Pydantic objects with .text attribute
    
    Args:
        message: LLM response message (AIMessage or similar)
        
    Returns:
        Extracted text content, stripped of whitespace
    """
    try:
        content = message.content
        if isinstance(content, str): 
            return content.strip()
        if isinstance(content, list):
            parts = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(str(b.get("text", "")))
                elif isinstance(b, str):
                    parts.append(b)
                elif hasattr(b, "text"):  # Pydantic object
                    parts.append(str(b.text))
                # Ignore other types (reasoning, etc.)
            return "\n".join(parts).strip()
        return str(content).strip()
    except Exception:
        # Fallback: try to get content as string
        if hasattr(message, "content"):
            return str(message.content).strip()
        return str(message).strip()
