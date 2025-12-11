from __future__ import annotations

import logging
from typing import Any, Dict

from .sub_agents import writer_review_agent

_LOGGER = logging.getLogger("article_agent.tools_article")


def writer_self_review(outline: str, section_notes: Any, draft_markdown: str) -> Dict[str, Any]:
    """Writer 自检工具：调用 writer_review_agent 并返回结构化结果。

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

    result = writer_review_agent(
        outline=outline,
        section_notes=section_notes,
        draft_markdown=draft_markdown,
    )
    data: Dict[str, Any] = {
        "needs_revision": bool(result.needs_revision),
        "comments": result.comments,
    }
    _LOGGER.debug("writer_self_review.result=%s", data)
    return data


__all__ = ["writer_self_review"]
