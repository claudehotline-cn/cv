"""Article Deep Agent Tools - Performance and Logging Utilities"""
from __future__ import annotations

import logging
import time
import re
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

_LOGGER = logging.getLogger("article_agent.deep_agent.utils.tools_logging")

@contextmanager
def log_performance(operation: str, **extra_info):
    """记录操作性能的上下文管理器。
    
    使用方式:
        with log_performance("write_section", section_id="sec_1"):
            # 执行操作
            pass
    """
    start_time = time.time()
    extra_str = ", ".join(f"{k}={v}" for k, v in extra_info.items())
    _LOGGER.info(f"[PERF] {operation} START {extra_str}")
    
    try:
        yield
    finally:
        elapsed_ms = (time.time() - start_time) * 1000
        _LOGGER.info(f"[PERF] {operation} END elapsed={elapsed_ms:.0f}ms {extra_str}")


def log_llm_response(operation: str, response, input_chars: int = 0):
    """记录 LLM 响应的详细信息，包括思维链。"""
    output_content = response.content if hasattr(response, 'content') else str(response)
    
    # Handle list content (LangChain v1 content_blocks)
    if isinstance(output_content, list):
        try:
            parts = []
            for b in output_content:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(str(b.get("text", "")))
                elif isinstance(b, str):
                    parts.append(b)
                else: 
                    parts.append(str(b))
            output_content = "\n".join(parts)
        except:
            output_content = str(output_content)
            
    if not isinstance(output_content, str):
        output_content = str(output_content)
    output_chars = len(output_content)
    
    # 提取思维链内容
    thinking_content = ""
    if hasattr(response, 'additional_kwargs'):
        thinking_content = response.additional_kwargs.get('reasoning_content', '')
    
    if not thinking_content:
        thinking_match = re.search(r'<think[^>]*>(.*?)</think>', output_content, re.DOTALL | re.IGNORECASE)
        thinking_content = thinking_match.group(1).strip() if thinking_match else ""
    
    # 尝试获取 token 使用信息（如果可用）
    token_info = ""
    if hasattr(response, 'response_metadata'):
        meta = response.response_metadata
        if 'prompt_eval_count' in meta:
            prompt_tokens = meta.get('prompt_eval_count', 0)
            completion_tokens = meta.get('eval_count', 0)
            total_tokens = prompt_tokens + completion_tokens
            token_info = f"prompt_tokens={prompt_tokens}, completion_tokens={completion_tokens}, total_tokens={total_tokens}"
        elif 'usage' in meta:
            usage = meta['usage']
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)
            total_tokens = usage.get('total_tokens', prompt_tokens + completion_tokens)
            token_info = f"prompt_tokens={prompt_tokens}, completion_tokens={completion_tokens}, total_tokens={total_tokens}"
    
    _LOGGER.info(
        f"[LLM] {operation} input_chars={input_chars}, output_chars={output_chars}, thinking_chars={len(thinking_content)}, {token_info}"
    )
    
    # 记录思维链内容（Chain of Thought）
    if thinking_content:
        thinking_preview = thinking_content[:2000]
        if len(thinking_content) > 2000:
            thinking_preview += "..."
        _LOGGER.info(
            f"[CHAIN_OF_THOUGHT] {operation}:\n"
            f"--- THINKING START ---\n"
            f"{thinking_preview}\n"
            f"--- THINKING END ---"
        )
    
    # 记录输出内容预览（移除思维链后的内容，最多 500 字符）
    actual_content = re.sub(r'<think[^>]*>.*?</think>', '', output_content, flags=re.DOTALL | re.IGNORECASE).strip()
    preview = actual_content[:500].replace('\n', '\\n')
    if len(actual_content) > 500:
        preview += "..."
    _LOGGER.info(f"[LLM_OUTPUT] {operation}: {preview}")


def log_tool_input(tool_name: str, **kwargs):
    """记录工具输入参数。"""
    params = ", ".join(f"{k}={str(v)[:100]}" for k, v in kwargs.items())
    _LOGGER.info(f"[TOOL_INPUT] {tool_name}: {params}")


def log_tool_output(tool_name: str, output: dict, preview_fields: list = None):
    """记录工具输出结果。
    
    Args:
        tool_name: 工具名称
        output: 输出字典
        preview_fields: 需要预览内容的字段列表
    """
    # 基本输出信息
    summary_fields = {k: v for k, v in output.items() if not isinstance(v, (dict, list)) or k in ['char_count', 'total_char_count']}
    _LOGGER.info(f"[TOOL_OUTPUT] {tool_name}: {summary_fields}")
    
    # 详细字段预览
    if preview_fields:
        for field in preview_fields:
            if field in output:
                content = str(output[field])
                preview = content[:300].replace('\n', '\\n')
                if len(content) > 300:
                    preview += "..."
                _LOGGER.info(f"[TOOL_OUTPUT_DETAIL] {tool_name}.{field}: {preview}")
