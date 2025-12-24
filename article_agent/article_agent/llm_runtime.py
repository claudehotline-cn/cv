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


def build_chat_llm(task_name: str = "article", enable_reasoning: bool = True) -> Any:
    """根据全局 Settings 构造用于内容整理的 Chat LLM 客户端。
    
    Args:
        task_name: 任务名称，用于日志
        enable_reasoning: 是否启用思维模式（Qwen3），结构化输出时应设为 False
    """

    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "ollama":
        _LOGGER.info(
            "llm.init provider=ollama task=%s model=%s base_url=%s num_predict=%s reasoning=%s",
            task_name,
            settings.llm_model,
            settings.ollama_base_url,
            settings.ollama_num_predict,
            enable_reasoning,
        )
        try:
            return ChatOllama(
                model=settings.llm_model,
                base_url=settings.ollama_base_url,
                temperature=0,
                reasoning=enable_reasoning,
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


def build_vlm_client(task_name: str = "vlm_analyze") -> Any:
    """构造用于图片理解的 VLM 客户端。
    
    使用 Ollama 的 VLM 模型（如 qwen3-vl:30b）进行图片语义分析。
    """
    settings = get_settings()
    
    if not getattr(settings, "vlm_enabled", True):
        return None
    
    vlm_model = getattr(settings, "vlm_model", "qwen3-vl:30b")
    
    _LOGGER.info(
        "vlm.init task=%s model=%s base_url=%s",
        task_name,
        vlm_model,
        settings.ollama_base_url,
    )
    
    try:
        return ChatOllama(
            model=vlm_model,
            base_url=settings.ollama_base_url,
            temperature=0,
        )
    except Exception as exc:  # pragma: no cover
        _LOGGER.error("vlm.init_failed task=%s error=%s", task_name, exc)
        return None


def build_structured_chat_llm(output_model: Type[TModel], task_name: str = "article") -> Any:
    """基于基础 Chat LLM 构造带结构化输出能力的 LLM。

    - output_model: 期望返回的 Pydantic 模型类型（如 PlannerOutput 等）；
    - task_name: 仅用于日志标识，区分不同子 Agent 调用场景。
    
    注意：结构化输出需要禁用 reasoning，否则 <think> 标签会破坏 JSON 解析。
    """

    # 结构化输出必须禁用 reasoning，否则思维过程会破坏 JSON 格式
    base_llm = build_chat_llm(task_name=task_name, enable_reasoning=False)

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


def invoke_with_structured_thinking(
    messages: list,
    output_model: Type[TModel],
    task_name: str = "article",
    timeout_sec: float = 180.0,
) -> tuple[str, TModel]:
    """调用 LLM 并同时获取思维过程和结构化输出。
    
    Args:
        messages: LangChain 消息列表
        output_model: 期望返回的 Pydantic 模型类型
        task_name: 任务名称，用于日志
        timeout_sec: 超时时间
    
    Returns:
        (thinking, structured_output) - 思维过程字符串和结构化输出对象
    
    工作原理：
        1. 使用 reasoning=True 的 LLM 进行调用
        2. 从响应中提取 <think>...</think> 内的思维过程
        3. 从响应中提取 JSON 部分并解析为 Pydantic 模型
    """
    import re
    import json
    
    # 构建启用思维模式的 LLM，并使用原生结构化输出
    settings = get_settings()
    from langchain_ollama import ChatOllama
    
    base_llm = ChatOllama(
        model=settings.llm_model,
        base_url=settings.ollama_base_url,
        temperature=0,
        reasoning=True,
        num_predict=16384,
    )
    
    # 使用 Ollama 原生的 json_schema 方法获取结构化输出
    try:
        llm = base_llm.with_structured_output(output_model, method="json_schema")
    except Exception as exc:
        _LOGGER.warning("invoke_with_structured_thinking.structured_output_failed task=%s error=%s, falling back to manual parsing", task_name, exc)
        llm = base_llm
    
    _LOGGER.info(
        "invoke_with_structured_thinking.init task=%s model=%s num_predict=16384 reasoning=True structured_output=%s",
        task_name, settings.llm_model, llm != base_llm
    )
    
    # 直接使用原始 messages，不添加额外格式指令
    enhanced_messages = list(messages)
    
    # 调用 LLM
    def _invoke():
        return llm.invoke(enhanced_messages)
    
    response = invoke_llm_with_timeout(task_name, _invoke, timeout_sec)
    
    # with_structured_output 可能直接返回 Pydantic 对象
    # 如果是的话，思考内容就丢失了
    # 但如果返回的是 AIMessage，需要解析
    
    thinking = ""
    structured_output = None
    
    # 检查是否直接是 Pydantic 对象
    if isinstance(response, output_model):
        structured_output = response
        _LOGGER.info(
            "invoke_with_structured_thinking.direct_output task=%s type=%s",
            task_name, type(response).__name__
        )
    else:
        # 是 AIMessage，需要解析
        response_text = ""
        thinking_from_kwargs = ""
        
        if hasattr(response, "content"):
            response_text = response.content or ""
        
        # 检查 additional_kwargs 中是否有思考内容
        if hasattr(response, "additional_kwargs"):
            kwargs = response.additional_kwargs or {}
            if "reasoning_content" in kwargs:
                thinking_from_kwargs = kwargs["reasoning_content"] or ""
            elif "thinking" in kwargs:
                thinking_from_kwargs = kwargs["thinking"] or ""
        
        # 记录响应结构用于调试
        _LOGGER.info(
            "invoke_with_structured_thinking.response task=%s content_len=%d thinking_kwargs_len=%d type=%s",
            task_name, len(response_text), len(thinking_from_kwargs), type(response).__name__
        )
        
        # 思考内容
        thinking = thinking_from_kwargs
        if not thinking:
            think_match = re.search(r'<think>(.*?)</think>', response_text, re.DOTALL | re.IGNORECASE)
            if think_match:
                thinking = think_match.group(1).strip()
                response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL | re.IGNORECASE)
        
        # 提取并解析 JSON
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response_text)
        if not json_match:
            json_match = re.search(r'\{[\s\S]*\}', response_text)
        
        if json_match:
            json_str = json_match.group(1) if '```json' in response_text else json_match.group(0)
            try:
                json_data = json.loads(json_str)
                structured_output = output_model.model_validate(json_data)
            except (json.JSONDecodeError, Exception) as exc:
                _LOGGER.warning(
                    "invoke_with_structured_thinking.parse_failed task=%s error=%s json=%s",
                    task_name, exc, json_str[:200]
                )
                raise ValueError(f"无法解析结构化输出: {exc}") from exc
        else:
            _LOGGER.warning(
                "invoke_with_structured_thinking.no_json task=%s response=%s",
                task_name, response_text[:200]
            )
            raise ValueError("响应中未找到 JSON 数据")
    
    _LOGGER.info(
        "invoke_with_structured_thinking.success task=%s thinking_len=%d",
        task_name, len(thinking)
    )
    
    return thinking, structured_output


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


async def astream_llm_with_thinking(
    llm: Any,
    messages: list,
    task_name: str,
) -> tuple[str, str]:
    """异步流式调用 LLM，分离思维过程和实际内容。
    
    通过 adispatch_custom_event 发送思维内容给前端。
    
    Args:
        llm: LangChain Chat LLM 实例
        messages: 消息列表
        task_name: 任务名称（用于日志和事件标识）
    
    Returns:
        (thinking_content, actual_content) - 思维内容和实际内容的元组
    """
    from langchain_core.callbacks import adispatch_custom_event
    import re
    
    thinking_buffer = ""
    content_buffer = ""
    in_thinking = False
    
    try:
        async for chunk in llm.astream(messages):
            # 获取 chunk 内容
            chunk_text = ""
            if hasattr(chunk, "content"):
                chunk_text = chunk.content or ""
            elif isinstance(chunk, str):
                chunk_text = chunk
            
            if not chunk_text:
                continue
            
            # 解析 <think> 标签
            # 处理可能跨 chunk 的标签
            full_text = (thinking_buffer if in_thinking else content_buffer) + chunk_text
            
            while True:
                if in_thinking:
                    # 寻找 </think> 结束标签
                    end_match = re.search(r"</think>", full_text, re.IGNORECASE)
                    if end_match:
                        # 发送思维内容到前端
                        thinking_part = full_text[:end_match.start()]
                        if thinking_part:
                            await adispatch_custom_event(
                                name="thinking",
                                data={"task": task_name, "content": thinking_part}
                            )
                            thinking_buffer += thinking_part
                        
                        full_text = full_text[end_match.end():]
                        in_thinking = False
                    else:
                        # 还在思维中，发送当前内容
                        if full_text:
                            await adispatch_custom_event(
                                name="thinking",
                                data={"task": task_name, "content": full_text}
                            )
                            thinking_buffer += full_text
                        break
                else:
                    # 寻找 <think> 开始标签
                    start_match = re.search(r"<think[^>]*>", full_text, re.IGNORECASE)
                    if start_match:
                        # 保存开始标签前的内容
                        content_before = full_text[:start_match.start()]
                        if content_before:
                            content_buffer += content_before
                        
                        full_text = full_text[start_match.end():]
                        in_thinking = True
                    else:
                        # 普通内容
                        content_buffer += full_text
                        break
        
        _LOGGER.debug(
            "astream_llm_with_thinking.done task=%s thinking_len=%d content_len=%d",
            task_name,
            len(thinking_buffer),
            len(content_buffer),
        )
        
    except Exception as exc:
        _LOGGER.error("astream_llm_with_thinking.error task=%s error=%s", task_name, exc)
        raise
    
    return thinking_buffer, content_buffer


__all__ = [
    "build_chat_llm",
    "build_vlm_client",
    "build_structured_chat_llm",
    "invoke_llm_with_timeout",
    "invoke_with_structured_thinking",
    "astream_llm_with_thinking",
]

