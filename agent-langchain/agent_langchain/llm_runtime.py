from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Dict, List, Union

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

from .config import get_settings

_LOGGER = logging.getLogger("agent_langchain.llm")


# ============================================================================
# Monkey Patch: Fix reasoning_content extraction (PR #34705)
# https://github.com/langchain-ai/langchain/pull/34705
# ============================================================================
def _apply_reasoning_content_patch():
    """Apply monkey patch to langchain_openai to preserve reasoning_content.
    
    This fixes the issue where vLLM's reasoning_content field is silently dropped
    when converting OpenAI responses to LangChain AIMessage objects.
    """
    try:
        import langchain_openai.chat_models.base as openai_base
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, FunctionMessage, ToolMessage, ChatMessage
        from typing import Mapping, cast
        
        # Store original function
        _original_convert_dict_to_message = openai_base._convert_dict_to_message
        
        def _patched_convert_dict_to_message(_dict: Mapping[str, Any]):
            """Patched version that preserves reasoning_content in additional_kwargs."""
            role = _dict.get("role")
            name = _dict.get("name")
            id_ = _dict.get("id")
            
            if role == "user":
                return HumanMessage(content=_dict.get("content", ""), id=id_, name=name)
            
            if role == "assistant":
                content = _dict.get("content", "") or ""
                additional_kwargs: dict = {}
                
                if function_call := _dict.get("function_call"):
                    additional_kwargs["function_call"] = dict(function_call)
                if audio := _dict.get("audio"):
                    additional_kwargs["audio"] = audio
                # 🚀 FIX: Preserve reasoning_content (PR #34705)
                if reasoning_content := _dict.get("reasoning_content"):
                    additional_kwargs["reasoning_content"] = reasoning_content
                    _LOGGER.info(f"[Patch] Extracted reasoning_content: {len(reasoning_content)} chars")
                # Also check for 'reasoning' field (vLLM uses both)
                if reasoning := _dict.get("reasoning"):
                    additional_kwargs["reasoning"] = reasoning
                    _LOGGER.info(f"[Patch] Extracted reasoning: {len(str(reasoning))} chars")
                
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
                    name=name,
                    id=id_,
                    tool_calls=tool_calls,
                    invalid_tool_calls=invalid_tool_calls,
                )
            
            # For other roles, use original function
            return _original_convert_dict_to_message(_dict)
        
        # Apply the patch
        openai_base._convert_dict_to_message = _patched_convert_dict_to_message
        _LOGGER.info("[Patch] Applied reasoning_content fix to langchain_openai")
        
    except Exception as e:
        _LOGGER.warning(f"[Patch] Failed to apply reasoning_content patch: {e}")


# Apply patch on module load
_apply_reasoning_content_patch()


def build_chat_llm(task_name: str = "generic") -> Any:
    """根据全局 Settings 构造用于对话/推理的 Chat LLM 客户端。"""

    settings = get_settings()
    provider = getattr(settings, "llm_provider", "openai").lower()

    if provider == "ollama":
        _LOGGER.info(
            "llm.init provider=ollama task=%s model=%s base_url=%s",
            task_name,
            settings.llm_model,
            getattr(settings, "ollama_base_url", "http://host.docker.internal:11434"),
        )
        try:
            return ChatOllama(
                model=settings.llm_model,
                base_url=getattr(settings, "ollama_base_url", "http://host.docker.internal:11434"),
                temperature=0,
                num_predict=24576,  # 用户请求 3 倍 token
                num_ctx=32768,      # 确保上下文窗口足够大
            )
        except Exception as exc:  # pragma: no cover
            _LOGGER.error("llm.init_failed provider=ollama task=%s error=%s", task_name, exc)
            raise RuntimeError(f"LLM 初始化失败（ollama, task={task_name}）") from exc

    if provider == "vllm":
        vllm_base_url = getattr(settings, "vllm_base_url", "http://vllm:8000/v1")
        _LOGGER.info(
            "llm.init provider=vllm task=%s model=%s base_url=%s thinking=enabled",
            task_name,
            settings.llm_model,
            vllm_base_url,
        )
        try:
            return ChatOpenAI(
                model=settings.llm_model,
                base_url=vllm_base_url,
                api_key="EMPTY",  # vLLM 不需要真正的 API key
                temperature=0.6,  # 🚀 Thinking Mode 推荐使用 0.6, 防止 suppression
                output_version="v1",  # 🚀 LangChain v1 标准化 content_blocks，分离 <think> 到 ReasoningContentBlock
                extra_body={
                    "chat_template_kwargs": {
                        "enable_thinking": True,  # 🚀 启用 Qwen3 思维模式
                    },
                },
                model_kwargs={
                    "stop": ["<|im_end|>", "<|endoftext|>"],
                },
            )
        except Exception as exc:  # pragma: no cover
            _LOGGER.error("llm.init_failed provider=vllm task=%s error=%s", task_name, exc)
            raise RuntimeError(f"LLM 初始化失败（vllm, task={task_name}）") from exc

    # 默认使用 openai 兼容接口
    if not settings.openai_api_key:
        _LOGGER.error("llm.init_failed provider=openai task=%s reason=missing_api_key", task_name)
        raise RuntimeError("OPENAI_API_KEY 未配置，无法初始化 LLM")

    _LOGGER.info(
        "llm.init provider=openai task=%s model=%s",
        task_name,
        settings.llm_model,
    )
    try:
        return ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key)
    except Exception as exc:  # pragma: no cover
        _LOGGER.error("llm.init_failed provider=openai task=%s error=%s", task_name, exc)
        raise RuntimeError(f"LLM 初始化失败（openai, task={task_name}）") from exc
