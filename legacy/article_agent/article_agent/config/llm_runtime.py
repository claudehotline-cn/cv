from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Type, TypeVar

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from .config import get_settings

_LOGGER = logging.getLogger("article_agent.llm")

TModel = TypeVar("TModel", bound=BaseModel)


def extract_text_content(response) -> str:
    """从 LLM 响应中提取文本内容。
    
    支持 LangChain v1 的 content_blocks 列表格式和传统字符串格式。
    
    Args:
        response: LLM 响应对象，可能有 content 属性（字符串或列表）
        
    Returns:
        提取的纯文本内容
    """
    try:
        content = response.content
        _LOGGER.debug(f"[extract_text_content] input type: {type(content)}")
        
        # 1. 优先尝试处理字符串
        if isinstance(content, str):
            return content.strip()
        
        # 2. 处理列表 (包括 list, Pydantic list 等)
        if isinstance(content, list) or hasattr(content, '__iter__'):
            _LOGGER.debug("[extract_text_content] processing iterable content")
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "unknown")
                    if block_type == "text":
                        text_parts.append(str(block.get("text", "")))
                    elif block_type == "reasoning":
                        pass
                    else:
                        text = block.get("text", "")
                        if text:
                            text_parts.append(str(text))
                elif isinstance(block, str):
                    text_parts.append(block)
                else:
                    # 兜底：尝试转为字符串
                    text_parts.append(str(block))
            return "\n".join(text_parts).strip()
            
        # 3. 兜底：强制转字符串
        return str(content).strip()

    except Exception as e:
        _LOGGER.error(f"[extract_text_content] failed: {e}")
        # 最后的防线：确保返回字符串
        return str(response.content if hasattr(response, 'content') else "").strip()


def extract_json_from_response(response: Any) -> Dict[str, Any]:
    """Helper to safely extract JSON from LLM response."""
    import json
    import re
    
    content = extract_text_content(response)
    
    # Try to find JSON block
    match = re.search(r'\{[\s\S]*\}', content)
    if match:
        json_str = match.group()
        # Fix common escape issues
        json_str = re.sub(r'\\([^"\\/bfnrtu])', r'\\\\\1', json_str)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
             # Aggressive fix: remove backslashes except before quotes
            json_str_fixed = re.sub(r'\\(?!")', '', json_str)
            return json.loads(json_str_fixed)
            
    # Fallback: try parsing the whole string if it looks like JSON
    try:
        return json.loads(content)
    except:
        pass
        
    return {}


def build_chat_llm(task_name: str = "article", num_ctx_override: int = None) -> Any:
    """根据全局 Settings 构造用于内容整理的 Chat LLM 客户端。
    
    Args:
        task_name: 任务名称，用于日志
        num_ctx_override: 可选，覆盖默认的上下文窗口大小（用于需要更大窗口的任务如 Illustrator）
    """

    settings = get_settings()
    provider = settings.llm_provider.lower()
    
    # 使用覆盖值或默认值
    actual_num_ctx = num_ctx_override if num_ctx_override else settings.ollama_num_ctx

    if provider == "ollama":
        _LOGGER.info(
            "llm.init provider=ollama task=%s model=%s base_url=%s num_predict=%s num_ctx=%s",
            task_name,
            settings.llm_model,
            settings.ollama_base_url,
            settings.ollama_num_predict,
            actual_num_ctx,
        )
        try:
            return ChatOllama(
                model=settings.llm_model,
                base_url=settings.ollama_base_url,
                temperature=0,
                num_predict=settings.ollama_num_predict,
                num_ctx=actual_num_ctx,
                timeout=600.0, # 10分钟超时，防止长文本任务中断
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

    if provider == "vllm":
        _LOGGER.info(
            "llm.init provider=vllm task=%s model=%s base_url=%s",
            task_name,
            settings.llm_model,
            settings.vllm_base_url,
        )
        try:
            return ChatOpenAI(
                model=settings.llm_model,
                base_url=settings.vllm_base_url,
                api_key="not-needed",
                temperature=0,
                timeout=600.0,
                # 使用 LangChain 1.0 content_blocks 标准化访问，将思考内容分离到 ReasoningContentBlock
                output_version="v1",
            )
        except Exception as exc:
            _LOGGER.error("llm.init_failed provider=vllm task=%s error=%s", task_name, exc)
            raise RuntimeError(f"LLM 初始化失败（vllm, task={task_name}）") from exc

    if provider == "gemini":
        if not settings.google_api_key:
            _LOGGER.error("llm.init_failed provider=gemini task=%s reason=missing_api_key", task_name)
            raise RuntimeError("GOOGLE_API_KEY 未配置，无法初始化 Gemini LLM")

        _LOGGER.info(
            "llm.init provider=gemini task=%s model=%s",
            task_name,
            settings.gemini_model,
        )
        try:
            return ChatGoogleGenerativeAI(
                model=settings.gemini_model,
                google_api_key=settings.google_api_key,
                temperature=0,
            )
        except Exception as exc:  # pragma: no cover
            _LOGGER.error("llm.init_failed provider=gemini task=%s error=%s", task_name, exc)
            raise RuntimeError(f"LLM 初始化失败（gemini, task={task_name}）") from exc

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
    
    支持 Ollama 和 vLLM 两种后端。
    """
    settings = get_settings()
    
    if not getattr(settings, "vlm_enabled", True):
        return None
    
    vlm_model = getattr(settings, "vlm_model", "qwen3-vl:30b")
    provider = settings.llm_provider.lower()
    
    # 使用 vLLM VLM 后端
    if provider == "vllm":
        _LOGGER.info(
            "vlm.init provider=vllm task=%s model=%s base_url=%s",
            task_name,
            vlm_model,
            settings.vllm_vl_base_url,
        )
        try:
            return ChatOpenAI(
                model=vlm_model,
                base_url=settings.vllm_vl_base_url,
                api_key="not-needed",
                temperature=0,
                timeout=600.0,
            )
        except Exception as exc:
            _LOGGER.error("vlm.init_failed provider=vllm task=%s error=%s", task_name, exc)
            return None
    
    # 默认使用 Ollama
    _LOGGER.info(
        "vlm.init provider=ollama task=%s model=%s base_url=%s",
        task_name,
        vlm_model,
        settings.ollama_base_url,
    )
    
    try:
        return ChatOllama(
            model=vlm_model,
            base_url=settings.ollama_base_url,
            temperature=0,
            timeout=600.0, # 10分钟超时
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


def invoke_with_structured_thinking(
    messages: list,
    output_model: Type[TModel],
    task_name: str = "article",
    timeout_sec: float = 600.0,
) -> tuple[str, TModel]:
    """调用 LLM 并获取结构化输出。
    
    Args:
        messages: LangChain 消息列表
        output_model: 期望返回的 Pydantic 模型类型
        task_name: 任务名称，用于日志
        timeout_sec: 超时时间
    
    Returns:
        (thinking, structured_output) - 思维过程字符串（空）和结构化输出对象
    
    工作原理：
        使用 Ollama 的 json_schema 方法强制输出 JSON 格式
    """
    settings = get_settings()
    from langchain_ollama import ChatOllama
    
    # 使用 reasoning=False，依赖 json_schema 保证 JSON 输出
    base_llm = ChatOllama(
        model=settings.llm_model,
        base_url=settings.ollama_base_url,
        temperature=0,
        reasoning=False,  # 禁用思维模式，保证 JSON 输出
        num_predict=16384,
    )
    
    # 使用 Ollama 原生的 json_schema 方法强制 JSON 输出
    llm = base_llm.with_structured_output(output_model, method="json_schema")
    
    _LOGGER.info(
        "invoke_with_structured_thinking.init task=%s model=%s reasoning=False json_schema=True",
        task_name, settings.llm_model
    )
    
    # 调用 LLM
    def _invoke():
        return llm.invoke(list(messages))
    
    response = invoke_llm_with_timeout(task_name, _invoke, timeout_sec)
    
    # with_structured_output + json_schema 直接返回 Pydantic 对象
    if not isinstance(response, output_model):
        raise ValueError(f"意外的响应类型: {type(response)}, 期望: {output_model}")
    
    _LOGGER.info(
        "invoke_with_structured_thinking.success task=%s output_type=%s",
        task_name, type(response).__name__
    )
    
    return "", response  # thinking 为空，因为 reasoning=False


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
        
        # 记录思维链内容到日志
        if thinking_buffer:
            _LOGGER.info(
                "astream_llm_with_thinking.thinking task=%s thinking_len=%d\n--- CHAIN OF THOUGHT ---\n%s\n--- END CHAIN OF THOUGHT ---",
                task_name,
                len(thinking_buffer),
                thinking_buffer[:3000] + ("..." if len(thinking_buffer) > 3000 else ""),
            )
        
        _LOGGER.info(
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
    "extract_text_content",
    "extract_json_from_response",
    "build_structured_chat_llm",
    "invoke_llm_with_timeout",
    "invoke_with_structured_thinking",
    "astream_llm_with_thinking",
]

