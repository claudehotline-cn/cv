from __future__ import annotations

import logging
from typing import Any, Dict

_LOGGER = logging.getLogger("article_agent.tools_article")


def writer_self_review(outline: str, section_notes: Any, draft_markdown: str) -> Dict[str, Any]:
    """Writer 自检工具（轻量规则版）：返回结构化结果。

    参数:
      outline: 文章大纲的文本描述（可以是简要说明或完整大纲）。
      section_notes: 研究笔记，可以是结构化对象（如 dict）或文本，由主 Agent 提供。
      draft_markdown: 当前的 Markdown 草稿。

    返回:
      {
        \"needs_revision\": bool,
        \"comments\": str
      }
    """

    total_chars = len((draft_markdown or "").strip())
    needs_revision = total_chars < 1500
    data: Dict[str, Any] = {
        "needs_revision": needs_revision,
        "comments": "草稿过短，建议按大纲扩写各章节" if needs_revision else "",
    }
    _LOGGER.debug("writer_self_review.result=%s", data)
    return data


__all__ = ["writer_self_review"]
