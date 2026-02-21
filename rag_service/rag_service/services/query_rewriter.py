"""Query expansion / rewriting (multi-query).

Uses vLLM-served LLM to generate alternative search queries.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from ..config import settings
from .llm_service import llm_service


logger = logging.getLogger(__name__)


def _extract_json_object(text: str) -> Optional[dict]:
    s = (text or "").strip()
    if not s:
        return None

    # Strip common thinking tags
    if "</think>" in s:
        s = s.split("</think>")[-1].strip()

    # Code fence
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()

    # Find first '{' ... matching '}'
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        ch = s[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = s[start : i + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    return None
    return None


class QueryRewriter:
    async def generate_multi_query(self, query: str) -> List[str]:
        q = (query or "").strip()
        if not q:
            return []

        system = """你是一个专业的搜索查询扩展助手。你的任务是根据用户的原始问题，生成 3 个不同角度的搜索查询词（Queries），以便在知识库中检索到相关文档。

要求：
1. 语义扩展：使用同义词、近义词替换核心概念。
2. 问题拆解：如果问题复杂，尝试拆分为更具体的子问题。
3. 关键信息提取：生成仅包含核心关键词的查询。
4. 输出必须是合法 JSON，包含一个 variations 列表。

输出示例：
{"variations": ["...", "...", "..."]}
"""

        raw = await llm_service.generate(
            q,
            model=settings.query_rewriter_model,
            timeout_sec=settings.query_rewriter_timeout_sec,
            temperature=0.5,
            system_prompt=system,
        )

        obj = None
        try:
            obj = json.loads(raw)
        except Exception:
            obj = _extract_json_object(raw)

        variations = []
        if isinstance(obj, dict) and isinstance(obj.get("variations"), list):
            for v in obj["variations"]:
                if isinstance(v, str) and v.strip():
                    variations.append(v.strip())

        # Always include original query and dedupe.
        out: List[str] = []
        seen = set()
        for v in [q] + variations:
            if v not in seen:
                out.append(v)
                seen.add(v)

        # Cap to avoid exploding costs.
        out = out[:4]
        logger.info("Generated %s queries from '%s': %s", len(out), q, out)
        return out


query_rewriter = QueryRewriter()
