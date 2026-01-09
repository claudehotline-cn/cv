from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Dict, List, Union

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

from .config import get_settings

_LOGGER = logging.getLogger("agent_langchain.llm")


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
            "llm.init provider=vllm task=%s model=%s base_url=%s",
            task_name,
            settings.llm_model,
            vllm_base_url,
        )
        try:
            return ChatOpenAI(
                model=settings.llm_model,
                base_url=vllm_base_url,
                api_key="EMPTY",  # vLLM 不需要真正的 API key
                temperature=0,
                model_kwargs={"stop": ["<|im_end|>", "<|endoftext|>"]},
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False},
                    "parallel_tool_calls": False,  # 🔴 强制禁用并发调用 (vLLM/OpenAI)
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


def build_structured_llm(schema: Any, task_name: str = "structured") -> Any:
    """构造配置了结构化输出的 LLM。
    
    使用 LangChain 的 with_structured_output() 方法确保 LLM 返回符合 Pydantic schema 的数据。
    
    Args:
        schema: Pydantic BaseModel 类，定义期望的输出格式
        task_name: 任务名称用于日志
        
    Returns:
        配置了结构化输出的 LLM，调用 invoke() 会直接返回 Pydantic 对象
    """
    base_llm = build_chat_llm(task_name=task_name)
    
    _LOGGER.info("llm.structured_output task=%s schema=%s", task_name, schema.__name__ if hasattr(schema, '__name__') else str(schema))
    
    try:
        return base_llm.with_structured_output(schema)
    except Exception as exc:
        _LOGGER.error("llm.structured_output_failed task=%s error=%s", task_name, exc)
        raise RuntimeError(f"结构化输出配置失败（task={task_name}）") from exc


def extract_text_content(response: Any) -> str:
    """从 LLM 响应中提取纯文本内容。
    
    支持 LangChain v1 的 content_blocks 列表格式和传统字符串格式。
    
    Args:
        response: LLM 响应对象 (AIMessage) 或内容字符串/列表
        
    Returns:
        提取的纯文本内容 (去除思维链和非文本块)
    """
    content = getattr(response, "content", response)
    
    # 1. Handle String
    if isinstance(content, str):
        return content.strip()
    
    # 2. Handle List (Content Blocks)
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type", "unknown")
                if block_type == "text":
                    text_parts.append(str(block.get("text", "")))
                # Ignore 'reasoning' or 'image' blocks for text extraction
            elif isinstance(block, str):
                text_parts.append(block)
        return "\n".join(text_parts).strip()
        
    return str(content)


def invoke_llm_with_timeout(
    task_name: str,
    fn: Callable[[], Any],
    timeout_sec: float,
) -> Any:
    """以统一的超时封装执行 LLM 调用函数。"""

    if timeout_sec is not None and timeout_sec <= 0:
        return fn()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        try:
            return future.result(timeout=timeout_sec)
        except FuturesTimeoutError as exc:
            _LOGGER.error("llm.timeout task=%s timeout_sec=%.1f", task_name, timeout_sec)
            raise TimeoutError(f"LLM 调用超时（task={task_name}, >{timeout_sec}s）") from exc

