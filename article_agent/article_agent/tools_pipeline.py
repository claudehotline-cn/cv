from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from .sub_agents import (
    assembler_agent,
    collector_agent,
    illustrator_agent,
    planner_agent,
    researcher_agent,
    writer_agent,
    writer_review_agent,
)

_LOGGER = logging.getLogger("article_agent.tools_pipeline")


@tool("collect_sources")
def collect_sources_tool(
    instruction: str,
    urls: Optional[List[str]] = None,
    file_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """步骤 1：轻量资料预取（Collector）。

    - 根据 instruction / urls / file_paths 生成每个来源的粗略概览 rough_sources_overview；
    - 不做精细分节，仅用于后续 Planner 理解整体资料分布。
    """

    overview = collector_agent(
        instruction=instruction,
        urls=urls or [],
        file_paths=file_paths or [],
    )
    result: Dict[str, Any] = {
        "instruction": instruction,
        "urls": urls or [],
        "file_paths": file_paths or [],
        "rough_sources_overview": overview,
    }
    _LOGGER.debug("collect_sources.result_len=%d", len(json.dumps(result, ensure_ascii=False)))
    return result


@tool("plan_outline")
def plan_outline_tool(
    instruction: str,
    rough_sources_overview: Optional[List[Dict[str, Any]]] = None,
    urls: Optional[List[str]] = None,
    file_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """步骤 2：Planner，根据资料概览与 instruction 设计大纲和研究计划。

    - 推荐先通过 collect_sources 获取 rough_sources_overview；
    - 如果未显式提供 rough_sources_overview，则会在内部调用 collector_agent 进行一次轻量预取。
    """

    if rough_sources_overview is None:
        _LOGGER.debug("plan_outline_tool: rough_sources_overview is None, fallback to collector_agent")
        rough_sources_overview = collector_agent(
            instruction=instruction,
            urls=urls or [],
            file_paths=file_paths or [],
        )

    planner_output = planner_agent(
        instruction=instruction,
        urls=[s.get("url", "") for s in rough_sources_overview if s.get("kind") == "url"],
        file_paths=[s.get("path", "") for s in rough_sources_overview if s.get("kind") == "file"],
        rough_sources_overview=rough_sources_overview,
    )
    result: Dict[str, Any] = {
        "instruction": instruction,
        "rough_sources_overview": rough_sources_overview,
        "urls": urls or [],
        "file_paths": file_paths or [],
        "outline": planner_output.outline,
        "sections_to_research": planner_output.sections_to_research,
    }
    _LOGGER.debug("plan_outline.result_keys=%s", list(result.keys()))
    return result


@tool("deep_research")
def deep_research_tool(
    outline: Any,
    sections_to_research: Any,
    urls: Optional[List[str]] = None,
    file_paths: Optional[List[str]] = None,
    article_id: Optional[str] = None,
) -> Dict[str, Any]:
    """步骤 3：深度 Researcher，根据大纲与研究计划整合 section_notes 和 image_metadata。"""

    research_output = researcher_agent(
        outline=outline,
        sections_to_research=sections_to_research,
        urls=urls or [],
        file_paths=file_paths or [],
    )
    result: Dict[str, Any] = {
        "outline": outline,
        "sections_to_research": sections_to_research,
        "urls": urls or [],
        "file_paths": file_paths or [],
        "article_id": article_id,
        "source_summaries": research_output.source_summaries,
        "section_notes": research_output.section_notes,
        "image_metadata": research_output.image_metadata,
    }
    _LOGGER.debug("deep_research.section_notes_keys=%s", list(research_output.section_notes.keys()))
    return result


@tool("write_markdown")
def write_markdown_tool(
    instruction: str,
    outline: Any,
    section_notes: Any,
    image_metadata: Any,
) -> Dict[str, Any]:
    """步骤 4：Writer，根据大纲与 section_notes 写出 Markdown 草稿。"""

    draft = writer_agent(
        instruction=instruction,
        outline=outline,
        section_notes=section_notes,
        image_metadata=image_metadata,
    )
    result: Dict[str, Any] = {
        "instruction": instruction,
        "outline": outline,
        "section_notes": section_notes,
        "image_metadata": image_metadata,
        "draft_markdown": draft,
    }
    _LOGGER.debug("write_markdown.draft_length=%d", len(draft))
    return result


@tool("review_markdown")
def review_markdown_tool(
    outline: Any,
    section_notes: Any,
    draft_markdown: str,
) -> Dict[str, Any]:
    """步骤 4b：Writer 自检，决定是否需要重写。"""

    review = writer_review_agent(
        outline=outline,
        section_notes=section_notes,
        draft_markdown=draft_markdown,
    )
    result: Dict[str, Any] = {
        "outline": outline,
        "section_notes": section_notes,
        "draft_markdown": draft_markdown,
        "needs_revision": bool(review.needs_revision),
        "comments": review.comments,
    }
    _LOGGER.debug("review_markdown.needs_revision=%s", result["needs_revision"])
    return result


@tool("curate_images")
def curate_images_tool(
    draft_markdown: str,
    image_metadata: Any,
    article_id: Optional[str] = None,
) -> Dict[str, Any]:
    """步骤 5：Illustrator，根据 image_metadata 在草稿中插入图片引用，生成 final_markdown。"""

    final_markdown = illustrator_agent(
        draft_markdown=draft_markdown,
        image_metadata=image_metadata,
    )
    result: Dict[str, Any] = {
        "article_id": article_id,
        "draft_markdown": draft_markdown,
        "image_metadata": image_metadata,
        "final_markdown": final_markdown,
    }
    _LOGGER.debug("curate_images.final_length=%d", len(final_markdown))
    return result


@tool("export_markdown_tool")
def export_markdown_tool(
    final_markdown: str,
    title: str,
    article_id: str,
) -> Dict[str, Any]:
    """步骤 6：Assembler，调用 export_markdown 落盘并返回下载链接等信息。"""

    info = assembler_agent(
        article_id=article_id,
        title=title,
        final_markdown=final_markdown,
    )
    output = info.get("output", {})
    result: Dict[str, Any] = {
        "article_id": output.get("article_id", article_id),
        "title": output.get("title", title),
        "md_path": output.get("md_path"),
        "md_url": output.get("md_url"),
    }
    _LOGGER.debug("export_markdown_tool.md_url=%s", result["md_url"])
    return result


__all__ = [
    "collect_sources_tool",
    "plan_outline_tool",
    "deep_research_tool",
    "write_markdown_tool",
    "review_markdown_tool",
    "curate_images_tool",
    "export_markdown_tool",
]
