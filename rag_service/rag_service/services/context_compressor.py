"""Context compression using vLLM-served LLM."""

from __future__ import annotations

import logging
from typing import List

from ..config import settings
from .llm_service import llm_service


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一个专业的信息提取助手。你的任务是从给定的文档片段中提取与用户问题最相关的内容。

规则：
1. 只保留与问题直接相关的句子或段落
2. 保持原文措辞，不要改写或总结
3. 如果整个片段都不相关，返回 "[无相关内容]"
4. 如果整个片段都相关，可以返回完整内容
5. 用 "..." 连接不连续的相关片段
6. 目标是将内容压缩到原来的 30-50%，同时保留所有关键信息
"""


class ContextCompressor:
    async def compress(self, query: str, content: str, max_length: int = 1500) -> str:
        if len(content) <= max_length:
            return content

        prompt = f"""用户问题：{query}

文档片段：
{content}

请提取与问题相关的内容："""

        try:
            compressed = await llm_service.generate(
                prompt,
                model=settings.llm_model,
                timeout_sec=settings.llm_timeout_sec,
                temperature=0.0,
                system_prompt=SYSTEM_PROMPT,
            )

            if "[无相关内容]" in compressed or len(compressed.strip()) < 50:
                return content

            ratio = len(compressed) / max(1, len(content))
            logger.info("Compressed content: %s -> %s chars (%.1f%%)", len(content), len(compressed), ratio * 100)
            return compressed.strip()
        except Exception as e:
            logger.error("Context compression failed: %s", e)
            return content

    async def compress_results(self, query: str, contents: List[str], max_length: int = 1500) -> List[str]:
        out: List[str] = []
        for c in contents:
            out.append(await self.compress(query, c, max_length=max_length))
        return out


context_compressor = ContextCompressor()
