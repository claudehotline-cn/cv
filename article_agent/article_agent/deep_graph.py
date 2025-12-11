from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from .content_state import ContentState
from .sub_agents import (
    assembler_agent,
    collector_agent,
    illustrator_agent,
    planner_agent,
    researcher_agent,
    section_writer_agent,
    doc_refiner_agent,
    writer_review_agent,
)

_LOGGER = logging.getLogger("article_agent.deep_graph")

MAX_RESEARCHER_RETRIES = 1
MAX_REFINER_RETRIES = 2


def _append_step(state: ContentState, step: str) -> ContentState:
    history = list(state.get("step_history", []))
    history.append(step)
    state["step_history"] = history
    return state


def entry_node(state: ContentState) -> ContentState:
    """入口节点：登记 instruction / urls / file_paths / article_id 到 State。"""

    _LOGGER.debug(
        "entry_node.instruction=%s urls=%s file_paths=%s article_id=%s",
        state.get("instruction", "")[:80],
        state.get("urls", []),
        state.get("file_paths", []),
        state.get("article_id", ""),
    )
    return _append_step(state, "entry")


def collector_node(state: ContentState) -> ContentState:
    """轻量资料预取节点：为 Planner 提供 rough_sources_overview。"""

    if state.get("error"):
        return _append_step(state, "collector_skipped")

    try:
        overview = collector_agent(
            instruction=state.get("instruction", ""),
            urls=state.get("urls", []),
            file_paths=state.get("file_paths", []),
        )
        new_state: ContentState = {
            **state,
            "rough_sources_overview": overview,
        }
        return _append_step(new_state, "collector")
    except Exception as exc:  # pragma: no cover - 防御性
        _LOGGER.error("collector_node.failed error=%s", exc)
        new_state = dict(state)
        new_state["error"] = f"collector_failed: {exc}"
        return _append_step(new_state, "collector_error")


def planner_node(state: ContentState) -> ContentState:
    if state.get("error"):
        return _append_step(state, "planner_skipped")

    try:
        result = planner_agent(
            instruction=state.get("instruction", ""),
            urls=state.get("urls", []),
            file_paths=state.get("file_paths", []),
            rough_sources_overview=state.get("rough_sources_overview"),
        )
        new_state: ContentState = {
            **state,
            "outline": result.outline,
            "sections_to_research": result.sections_to_research,
        }
        return _append_step(new_state, "planner")
    except Exception as exc:  # pragma: no cover - 防御性
        _LOGGER.error("planner_node.failed error=%s", exc)
        new_state = dict(state)
        new_state["error"] = f"planner_failed: {exc}"
        return _append_step(new_state, "planner_error")


def researcher_node(state: ContentState) -> ContentState:
    if state.get("error"):
        return _append_step(state, "researcher_skipped")

    try:
        result = researcher_agent(
            outline=state.get("outline"),
            sections_to_research=state.get("sections_to_research"),
            urls=state.get("urls", []),
            file_paths=state.get("file_paths", []),
        )
        attempts = int(state.get("researcher_attempts", 0) or 0) + 1
        new_state: ContentState = {
            **state,
            "source_summaries": result.source_summaries,
            "section_notes": result.section_notes,
            "image_metadata": result.image_metadata,
            "researcher_attempts": attempts,
        }
        return _append_step(new_state, "researcher")
    except Exception as exc:  # pragma: no cover - 防御性
        _LOGGER.error("researcher_node.failed error=%s", exc)
        new_state = dict(state)
        new_state["error"] = f"researcher_failed: {exc}"
        return _append_step(new_state, "researcher_error")


def section_writer_node(state: ContentState) -> ContentState:
    """Section Writer 节点：按小节逐段生成 Markdown 片段。"""

    if state.get("error"):
        return _append_step(state, "section_writer_skipped")

    try:
        section_notes = state.get("section_notes") or {}
        section_drafts = section_writer_agent(
            instruction=state.get("instruction", ""),
            outline=state.get("outline"),
            section_notes=section_notes if isinstance(section_notes, dict) else {},
        )
        new_state: ContentState = {
            **state,
            "section_drafts": section_drafts,
        }
        return _append_step(new_state, "section_writer")
    except Exception as exc:  # pragma: no cover
        _LOGGER.error("section_writer_node.failed error=%s", exc)
        new_state = dict(state)
        new_state["error"] = f"section_writer_failed: {exc}"
        return _append_step(new_state, "section_writer_error")


def merge_sections_node(state: ContentState) -> ContentState:
    """Merge 节点：按 section_drafts 顺序合并为完整草稿 draft_markdown。"""

    if state.get("error"):
        return _append_step(state, "merge_sections_skipped")

    section_drafts = state.get("section_drafts") or {}
    outline = state.get("outline")
    merged_parts: list[str] = []

    # 优先按 outline 中出现的 section_id 顺序合并；若无法解析 outline，则退回到插入顺序。
    used_ids: set[str] = set()

    if isinstance(outline, list) and isinstance(section_drafts, dict):
        for item in outline:
            section_id: str | None = None
            if isinstance(item, dict):
                # 兼容不同字段命名：id / section_id / key
                for key in ("id", "section_id", "key"):
                    if key in item and item[key] is not None:
                        section_id = str(item[key])
                        break
            elif isinstance(item, str):
                section_id = item

            if not section_id:
                continue

            text = section_drafts.get(section_id)
            if isinstance(text, str) and text.strip():
                merged_parts.append(text.strip())
                used_ids.add(section_id)

        # 将 outline 中未提及的剩余 section_drafts 追加在末尾，避免内容丢失。
        for sec_id, text in section_drafts.items():
            if sec_id in used_ids:
                continue
            if isinstance(text, str) and text.strip():
                merged_parts.append(text.strip())
    elif isinstance(section_drafts, dict):
        for text in section_drafts.values():
            if isinstance(text, str) and text.strip():
                merged_parts.append(text.strip())

    draft = "\n\n".join(merged_parts).strip()
    new_state: ContentState = {
        **state,
        "draft_markdown": draft,
        "refined_markdown": draft,
        # 每次从 merge 开始视为新的 refine 流程
        "refine_round": 0,
    }
    return _append_step(new_state, "merge_sections")


def doc_refiner_node(state: ContentState) -> ContentState:
    """Doc Refiner 节点：对当前 draft_markdown 做一次通篇重写。"""

    if state.get("error"):
        return _append_step(state, "doc_refiner_skipped")

    draft = state.get("draft_markdown") or ""
    refine_round = int(state.get("refine_round", 0) or 0)

    try:
        refined = doc_refiner_agent(
            instruction=state.get("instruction", ""),
            draft_markdown=draft,
        )
        new_round = refine_round + 1
        final_text = refined or draft
        new_state: ContentState = {
            **state,
            "draft_markdown": final_text,
            "refined_markdown": final_text,
            "refine_round": new_round,
        }
        return _append_step(new_state, "doc_refiner")
    except Exception as exc:  # pragma: no cover
        _LOGGER.error("doc_refiner_node.failed error=%s", exc)
        new_state = dict(state)
        new_state["error"] = f"doc_refiner_failed: {exc}"
        return _append_step(new_state, "doc_refiner_error")


def illustrator_node(state: ContentState) -> ContentState:
    if state.get("error"):
        return _append_step(state, "illustrator_skipped")

    # 若无可用图片，则走无图降级路径：直接复用草稿并记录原因
    images = state.get("image_metadata") or {}
    has_images = False
    if isinstance(images, dict):
        for items in images.values():
            if items:
                has_images = True
                break

    if not has_images:
        new_state: ContentState = {
            **state,
            "final_markdown": state.get("draft_markdown"),
            "illustrator_skip_reason": "no_images",
        }
        return _append_step(new_state, "illustrator_skipped_no_images")

    try:
        updated = illustrator_agent(
            draft_markdown=state.get("draft_markdown") or "",
            image_metadata=state.get("image_metadata"),
        )
        new_state: ContentState = {**state, "final_markdown": updated}
        return _append_step(new_state, "illustrator")
    except Exception as exc:  # pragma: no cover
        _LOGGER.error("illustrator_node.failed error=%s", exc)
        new_state = dict(state)
        new_state["error"] = f"illustrator_failed: {exc}"
        return _append_step(new_state, "illustrator_error")


def assembler_node(state: ContentState) -> ContentState:
    # 即使上游出错也尝试执行，以便在部分场景返回已有 draft/final_markdown。
    try:
        info = assembler_agent(
            article_id=state.get("article_id", ""),
            title=state.get("title", "未命名文章"),
            final_markdown=state.get("final_markdown") or state.get("draft_markdown") or "",
        )
        new_state: ContentState = {
            **state,
            "download_info": info.get("output", {}),
        }
        return _append_step(new_state, "assembler")
    except Exception as exc:  # pragma: no cover
        _LOGGER.error("assembler_node.failed error=%s", exc)
        new_state = dict(state)
        new_state["error"] = f"assembler_failed: {exc}"
        return _append_step(new_state, "assembler_error")


def writer_review_node(state: ContentState) -> ContentState:
    """Writer 自检节点：决定是否需要重写。"""

    if state.get("error"):
        return _append_step(state, "writer_review_skipped")

    try:
        review = writer_review_agent(
            outline=state.get("outline"),
            section_notes=state.get("section_notes"),
            draft_markdown=state.get("draft_markdown") or "",
        )
        new_state: ContentState = {
            **state,
            "writer_review": review.comments,
            "writer_needs_revision": review.needs_revision,
        }
        return _append_step(new_state, "writer_review")
    except Exception as exc:  # pragma: no cover
        _LOGGER.error("writer_review_node.failed error=%s", exc)
        new_state = dict(state)
        new_state["error"] = f"writer_review_failed: {exc}"
        return _append_step(new_state, "writer_review_error")


def researcher_router(state: ContentState) -> str:
    """根据 Researcher 结果决定下一步：重试或进入 Writer。"""

    if state.get("error"):
        return "skip"

    attempts = int(state.get("researcher_attempts", 0) or 0)
    summaries = state.get("source_summaries") or {}
    has_sources = isinstance(summaries, dict) and bool(summaries)

    if (not has_sources) and attempts < MAX_RESEARCHER_RETRIES and (state.get("urls") or state.get("file_paths")):
        return "retry"
    return "next"


def writer_review_router(state: ContentState) -> str:
    """根据 Writer 自检结果与草稿质量信号决定是否再次 Refiner 或进入 Illustrator。"""

    if state.get("error"):
        return "skip"

    refine_round = int(state.get("refine_round", 0) or 0)
    needs_revision = bool(state.get("writer_needs_revision"))

    # 基于草稿长度与“小结”信号的自动质量检测
    draft = state.get("draft_markdown") or ""
    draft_len = len(draft)
    has_multiple_sections = draft.count("\n## ") + draft.count("\n### ") >= 2
    has_small_summary = "小结" in draft

    auto_needs_revision = False
    MIN_DRAFT_LENGTH_CHARS = 1500

    # 草稿过短且已有多节内容，倾向于再 refine 一轮。
    if has_multiple_sections and draft_len > 0 and draft_len < MIN_DRAFT_LENGTH_CHARS:
        auto_needs_revision = True

    # 多节文章但几乎没有“小结”，提示再 refine 一轮补充节末小结。
    if has_multiple_sections and not has_small_summary:
        auto_needs_revision = True

    effective_needs_revision = needs_revision or auto_needs_revision

    if effective_needs_revision and refine_round < MAX_REFINER_RETRIES:
        return "retry"
    return "next"


def get_content_graph():
    graph = StateGraph(ContentState)
    graph.add_node("entry", entry_node)
    graph.add_node("collector", collector_node)
    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("section_writer", section_writer_node)
    graph.add_node("merge_sections", merge_sections_node)
    graph.add_node("doc_refiner", doc_refiner_node)
    graph.add_node("writer_review", writer_review_node)
    graph.add_node("illustrator", illustrator_node)
    graph.add_node("assembler", assembler_node)

    graph.set_entry_point("entry")
    graph.add_edge("entry", "collector")
    graph.add_edge("collector", "planner")
    graph.add_edge("planner", "researcher")
    graph.add_conditional_edges(
        "researcher",
        researcher_router,
        {
            "retry": "researcher",
            "next": "section_writer",
            "skip": "section_writer",
        },
    )
    graph.add_edge("section_writer", "merge_sections")
    graph.add_edge("merge_sections", "doc_refiner")
    graph.add_edge("doc_refiner", "writer_review")
    graph.add_conditional_edges(
        "writer_review",
        writer_review_router,
        {
            "retry": "doc_refiner",
            "next": "illustrator",
            "skip": "illustrator",
        },
    )
    graph.add_edge("illustrator", "assembler")
    graph.add_edge("assembler", END)

    return graph.compile()


__all__ = ["get_content_graph"]
