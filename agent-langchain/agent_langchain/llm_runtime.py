from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable

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

