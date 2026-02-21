"""LLM service wrapper.

LLM and VLM are served by vLLM (OpenAI-compatible API).
Embeddings remain served by Ollama.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from ..config import settings
from .vllm_client import chat_completion, chat_completion_stream


logger = logging.getLogger(__name__)


class LLMService:
    async def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        timeout_sec: Optional[int] = None,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self.generate_messages(
            messages,
            model=model,
            timeout_sec=timeout_sec,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def generate_messages(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        timeout_sec: Optional[int] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        used_model = (model or settings.llm_model).strip()
        timeout = int(timeout_sec if timeout_sec is not None else settings.llm_timeout_sec)
        return await chat_completion(
            base_url=settings.vllm_base_url,
            api_key=settings.vllm_api_key,
            model=used_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_sec=timeout,
        )

    async def stream_messages(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        timeout_sec: Optional[int] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        used_model = (model or settings.llm_model).strip()
        timeout = int(timeout_sec if timeout_sec is not None else settings.llm_timeout_sec)
        async for chunk in chat_completion_stream(
            base_url=settings.vllm_base_url,
            api_key=settings.vllm_api_key,
            model=used_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_sec=timeout,
        ):
            yield chunk


llm_service = LLMService()
