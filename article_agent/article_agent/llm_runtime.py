from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Type, TypeVar

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from pydantic import BaseModel

from .config import get_settings

_LOGGER = logging.getLogger("article_agent.llm")

TModel = TypeVar("TModel", bound=BaseModel)


def build_chat_llm(task_name: str = "article") -> Any:
    """根据全局 Settings 构造用于内容整理的 Chat LLM 客户端。"""

    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "ollama":
        _LOGGER.info(
            "llm.init provider=ollama task=%s model=%s base_url=%s num_predict=%s",
            task_name,
            settings.llm_model,
            settings.ollama_base_url,
            settings.ollama_num_predict,
        )
        try:
            return ChatOllama(
                model=settings.llm_model,
                base_url=settings.ollama_base_url,
                temperature=0,
                reasoning=False,
                num_predict=settings.ollama_num_predict,
            )
        except Exception as exc:  # pragma: no cover
            _LOGGER.error("llm.init_failed provider=ollama task=%s error=%s", task_name, exc)
            raise RuntimeError(f"LLM 初始化失败（ollama, task={task_name}）") from exc

    if provider == "siliconflow":
        if not settings.siliconflow_api_key:
            _LOGGER.error("llm.init_failed provider=siliconflow task=%s reason=missing_api_key", task_name)
            raise RuntimeError("SILICONFLOW_API_KEY 未配置，无法初始化 SiliconFlow LLM")

        _LOGGER.info(
            "llm.init provider=siliconflow task=%s model=%s base_url=%s",
            task_name,
            settings.llm_model,
            settings.siliconflow_base_url,
        )
        try:
            return ChatOpenAI(
                model=settings.llm_model,
                api_key=settings.siliconflow_api_key,
                base_url=settings.siliconflow_base_url,
            )
        except Exception as exc:  # pragma: no cover
            _LOGGER.error("llm.init_failed provider=siliconflow task=%s error=%s", task_name, exc)
            raise RuntimeError(f"LLM 初始化失败（siliconflow, task={task_name}）") from exc

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


def build_structured_chat_llm(output_model: Type[TModel], task_name: str = "article") -> Any:
    """基于基础 Chat LLM 构造带结构化输出能力的 LLM。

    - output_model: 期望返回的 Pydantic 模型类型（如 PlannerOutput 等）；
    - task_name: 仅用于日志标识，区分不同子 Agent 调用场景。
    """

    base_llm = build_chat_llm(task_name=task_name)

    try:
        # 通过 LangChain 的 structured output 功能，让 LLM 直接按 Pydantic 模型输出结构化结果。
        structured_llm = base_llm.with_structured_output(output_model)  # type: ignore[attr-defined]
    except AttributeError as exc:  # pragma: no cover - 结构化输出能力缺失
        raise RuntimeError(
            f"当前 Chat LLM 不支持 with_structured_output，无法为 task={task_name} 生成结构化输出"
        ) from exc
    except Exception as exc:  # pragma: no cover - 防御性
        raise RuntimeError(f"LLM 结构化输出初始化失败（task={task_name}）: {exc}") from exc

    return structured_llm


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
            raise TimeoutError(f"LLM 调用超时（task=%s, >%.1fs）" % (task_name, timeout_sec)) from exc


__all__ = ["build_chat_llm", "build_structured_chat_llm", "invoke_llm_with_timeout"]
