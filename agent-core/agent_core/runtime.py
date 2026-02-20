from __future__ import annotations

import logging
from typing import Any, Mapping, Callable, Type, TypeVar

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_core.messages import AIMessage, AIMessageChunk
from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)

from .settings import get_settings

_LOGGER = logging.getLogger("agent_core.runtime")


# ============================================================================
# Monkey Patch: Fix reasoning_content extraction
# ============================================================================
def _apply_reasoning_content_patch():
    """Apply monkey patch to langchain_openai to preserve reasoning_content."""
    try:
        import langchain_openai.chat_models.base as openai_base
        
        # Store original functions
        _original_convert_dict_to_message = openai_base._convert_dict_to_message
        _original_convert_delta = openai_base._convert_delta_to_message_chunk
        
        # Patch 1: Non-streaming
        def _patched_convert_dict_to_message(_dict: Mapping[str, Any]):
            role = _dict.get("role")
            if role == "assistant":
                reasoning = _dict.get("reasoning_content") or _dict.get("reasoning")
                if not reasoning:
                     return _original_convert_dict_to_message(_dict)
                
                content = _dict.get("content", "") or ""
                additional_kwargs: dict = {}
                
                if function_call := _dict.get("function_call"):
                    additional_kwargs["function_call"] = dict(function_call)
                if audio := _dict.get("audio"):
                    additional_kwargs["audio"] = audio
                
                additional_kwargs["reasoning_content"] = reasoning
                
                tool_calls = []
                invalid_tool_calls = []
                if raw_tool_calls := _dict.get("tool_calls"):
                    from langchain_core.output_parsers.openai_tools import parse_tool_call, make_invalid_tool_call
                    for raw_tool_call in raw_tool_calls:
                        try:
                            tool_calls.append(parse_tool_call(raw_tool_call, return_id=True))
                        except Exception as e:
                            invalid_tool_calls.append(make_invalid_tool_call(raw_tool_call, str(e)))
                
                return AIMessage(
                    content=content,
                    additional_kwargs=additional_kwargs,
                    name=_dict.get("name"),
                    id=_dict.get("id"),
                    tool_calls=tool_calls,
                    invalid_tool_calls=invalid_tool_calls,
                )
            return _original_convert_dict_to_message(_dict)
        
        # Patch 2: Streaming
        def _patched_convert_delta_to_message_chunk(_dict, default_class):
            chunk = _original_convert_delta(_dict, default_class)
            reasoning = _dict.get("reasoning_content") or _dict.get("reasoning")
            if reasoning and isinstance(chunk, AIMessageChunk):
                chunk.additional_kwargs["reasoning_content"] = reasoning
            return chunk

        openai_base._convert_dict_to_message = _patched_convert_dict_to_message
        openai_base._convert_delta_to_message_chunk = _patched_convert_delta_to_message_chunk
        _LOGGER.info("[Patch] Applied reasoning_content fix to langchain_openai")
        
    except Exception as e:
        _LOGGER.warning(f"[Patch] Failed to apply reasoning_content patch: {e}")

_apply_reasoning_content_patch()


def build_chat_llm(task_name: str = "generic") -> Any:
    """Build Chat LLM client based on settings."""

    settings = get_settings()
    provider = getattr(settings, "llm_provider", "openai").lower()

    if provider == "ollama":
        _LOGGER.info(f"llm.init provider=ollama task={task_name} model={settings.llm_model}")
        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=0,
            num_predict=8192,
        )

    if provider == "vllm":
        _LOGGER.info(f"llm.init provider=vllm task={task_name} model={settings.llm_model} thinking=enabled")
        return ChatOpenAI(
            model=settings.llm_model,
            name=task_name,
            base_url=settings.vllm_base_url,
            api_key="EMPTY",
            temperature=0.6,
            output_version="v1",
            streaming=True,
            max_tokens=settings.llm_max_tokens,
            extra_body={
                "chat_template_kwargs": {
                    "enable_thinking": True,
                },
            }
        )

    # OpenAI Default
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    _LOGGER.info(f"llm.init provider=openai task={task_name} model={settings.llm_model}")
    return ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key)

