from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from .config import get_settings
from .content_state import ContentState
from .sub_agents import (
    assembler_agent,
    collector_agent,
    doc_refiner_agent,
    illustrator_agent,
    planner_agent,
    reader_review_agent,
    researcher_agent,
    section_writer_agent,
)
from .workflow_utils import dedupe_preserve_order, ensure_article_id, add_heading_numbers

_LOGGER = logging.getLogger("article_agent.deep_graph")

MAX_RESEARCH_ROUNDS = 2
MAX_REWRITE_ROUNDS = 2

MIN_IMPORTANT_NOTE_CHARS = 300
MIN_TOTAL_DRAFT_CHARS = 3000
MIN_CORE_SECTION_CHARS = 800
MIN_NORMAL_SECTION_CHARS = 400


def _append_step(state: ContentState, step: str) -> ContentState:
    history = list(state.get("step_history", []))
    history.append(step)
    state["step_history"] = history
    return state


def init_node(state: ContentState) -> ContentState:
    """init：清洗输入、初始化计数器。"""

    urls = dedupe_preserve_order(state.get("urls", []) or [])
    file_paths = dedupe_preserve_order(state.get("file_paths", []) or [])

    new_state: ContentState = {
        **state,
        "urls": urls,
        "file_paths": file_paths,
        "article_id": ensure_article_id(state.get("article_id")),
        "rewrite_round": int(state.get("rewrite_round", 0) or 0),
        "research_round": int(state.get("research_round", 0) or 0),
        "sections_to_rewrite": list(state.get("sections_to_rewrite", []) or []),
    }
    return _append_step(new_state, "init")


def collector_node(state: ContentState) -> ContentState:
    if state.get("error"):
        return _append_step(state, "collector_skipped")

    sources, overview = collector_agent(
        urls=state.get("urls", []) or [],
        file_paths=state.get("file_paths", []) or [],
    )
    new_state: ContentState = {
        **state,
        "sources": sources,
        "rough_sources_overview": overview,
    }
    return _append_step(new_state, "collector")


def planner_node(state: ContentState) -> ContentState:
    if state.get("error"):
        return _append_step(state, "planner_skipped")

    outline_model = planner_agent(
        instruction=state.get("instruction", "") or "",
        rough_sources_overview=state.get("rough_sources_overview") or {},
    )
    outline_dict = outline_model.model_dump()
    title = (state.get("title") or "").strip() or outline_model.title

    new_state: ContentState = {
        **state,
        "title": title,
        "outline": outline_dict,
        "sections_to_research": list(outline_model.sections_to_research or []),
    }
    return _append_step(new_state, "planner")


def researcher_node(state: ContentState) -> ContentState:
    if state.get("error"):
        return _append_step(state, "researcher_skipped")

    research_round = int(state.get("research_round", 0) or 0)
    target_section_ids: Optional[List[str]] = None
    if research_round > 0:
        target_section_ids = dedupe_preserve_order(
            (state.get("research_missing_important", []) or [])
            + (state.get("research_weak_important", []) or [])
        )

    output, extra_keys = researcher_agent(
        outline=state.get("outline") or {},
        sections_to_research=state.get("sections_to_research", []) or [],
        sources=state.get("sources", {}) or {},
        target_section_ids=target_section_ids,
    )

    # 合并策略：首次全量写入；补全时仅覆盖目标节，保留既有内容。
    if target_section_ids:
        merged_notes = dict(state.get("section_notes") or {})
        merged_images = dict(state.get("image_metadata") or {})
        merged_notes.update(output.section_notes or {})
        merged_images.update(output.image_metadata or {})
        section_notes = merged_notes
        image_metadata = merged_images
    else:
        section_notes = output.section_notes or {}
        image_metadata = output.image_metadata or {}

    new_state: ContentState = {
        **state,
        "section_notes": section_notes,
        "image_metadata": image_metadata,
        "source_summaries": output.source_summaries or {},
        "research_extra_keys": extra_keys,
        "research_round": research_round + 1,
        "research_error": None,
    }
    return _append_step(new_state, "researcher")


def _is_no_data(text: str) -> bool:
    value = (text or "").strip()
    return (not value) or value.upper().startswith("NO_DATA")


def research_audit_node(state: ContentState) -> ContentState:
    """research_audit：规则质检，不用 LLM。"""

    outline = state.get("outline") or {}
    sections = outline.get("sections") if isinstance(outline, dict) else None
    section_ids: List[str] = []
    if isinstance(sections, list):
        for sec in sections:
            if isinstance(sec, dict) and sec.get("id"):
                section_ids.append(str(sec["id"]))

    section_notes = state.get("section_notes") or {}
    if not isinstance(section_notes, dict):
        section_notes = {}

    missing_all: List[str] = []
    for sec_id in section_ids:
        note = section_notes.get(sec_id)
        if not isinstance(note, str) or _is_no_data(note):
            missing_all.append(sec_id)

    important_ids = set(state.get("sections_to_research", []) or [])
    missing_important = [sec_id for sec_id in missing_all if sec_id in important_ids]

    weak_important: List[str] = []
    for sec_id in important_ids:
        note = section_notes.get(sec_id)
        if not isinstance(note, str) or _is_no_data(note):
            continue
        if len(note.strip()) < MIN_IMPORTANT_NOTE_CHARS:
            weak_important.append(sec_id)

    research_ok = (not missing_important) and (not weak_important)
    research_error: Optional[str] = None
    if not research_ok:
        research_error = (
            f"missing_important={missing_important} weak_important={weak_important}"
        )

    new_state: ContentState = {
        **state,
        "research_missing_all": missing_all,
        "research_missing_important": missing_important,
        "research_weak_important": weak_important,
        "research_ok": research_ok,
        "research_error": research_error,
    }
    return _append_step(new_state, "research_audit")


def research_router(state: ContentState) -> str:
    if state.get("error"):
        return "next"

    ok = bool(state.get("research_ok"))
    research_round = int(state.get("research_round", 0) or 0)
    if ok or research_round >= MAX_RESEARCH_ROUNDS:
        return "next"
    return "retry"


def section_writer_node(state: ContentState) -> ContentState:
    if state.get("error"):
        return _append_step(state, "section_writer_skipped")

    rewrite_round = int(state.get("rewrite_round", 0) or 0)
    target_section_ids: Optional[List[str]] = None
    existing_section_drafts: Optional[Dict[str, str]] = None

    if rewrite_round > 0:
        target_section_ids = state.get("sections_to_rewrite") or []
        existing_section_drafts = state.get("section_drafts") or {}

    drafts = section_writer_agent(
        instruction=state.get("instruction", "") or "",
        outline=state.get("outline") or {},
        section_notes=state.get("section_notes") or {},
        image_metadata=state.get("image_metadata") or {},
        target_section_ids=target_section_ids,
        existing_section_drafts=existing_section_drafts,
    )

    new_state: ContentState = {**state, "section_drafts": drafts}
    return _append_step(new_state, "section_writer")


def _section_body_chars(markdown: str) -> int:
    if not isinstance(markdown, str) or not markdown.strip():
        return 0
    lines = markdown.splitlines()
    if lines and re.match(r"^[ \t]*#{1,6}[ \t]+", lines[0]):
        body = "\n".join(lines[1:])
    else:
        body = markdown
    return len(body.strip())


def writer_audit_node(state: ContentState) -> ContentState:
    """writer_audit：规则质检，不用 LLM。"""

    outline = state.get("outline") or {}
    sections = outline.get("sections") if isinstance(outline, dict) else None
    if not isinstance(sections, list):
        sections = []

    drafts = state.get("section_drafts") or {}
    if not isinstance(drafts, dict):
        drafts = {}

    image_metadata = state.get("image_metadata") or {}
    if not isinstance(image_metadata, dict):
        image_metadata = {}

    missing_sections: List[str] = []
    short_sections: List[str] = []
    missing_image_placeholders: List[str] = []
    invalid_image_placeholders: List[str] = []
    per_section_chars: Dict[str, int] = {}

    total_chars = 0
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        sec_id = str(sec.get("id") or "").strip()
        if not sec_id:
            continue
        is_core = bool(sec.get("is_core"))
        min_chars = MIN_CORE_SECTION_CHARS if is_core else MIN_NORMAL_SECTION_CHARS

        draft_text = str(drafts.get(sec_id) or "")
        body_chars = _section_body_chars(draft_text)
        per_section_chars[sec_id] = body_chars
        total_chars += body_chars

        if body_chars <= 0:
            missing_sections.append(sec_id)
        elif body_chars < min_chars:
            short_sections.append(sec_id)

        # 若 Researcher 为本节提供了图片，但 Writer 没输出任何本节占位符，则要求重写该节。
        candidates = image_metadata.get(sec_id) or []
        if isinstance(candidates, list) and candidates:
            # 1) 必须至少有一个本节占位符
            placeholders = re.findall(
                rf"<!--\s*IMAGE\s*:\s*{re.escape(sec_id)}\s*(?::\s*(\d+)\s*)?(?:\|\s*.*?\s*)?-->",
                draft_text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not placeholders:
                missing_image_placeholders.append(sec_id)
            else:
                # 2) 占位符数量不应超过候选图片数（避免过多插图导致阅读负担与错配）
                if len(placeholders) > len(candidates):
                    invalid_image_placeholders.append(sec_id)
                    continue

                # 3) 若 Writer 选择了 :n，则 n 必须在有效范围内（1..len(candidates)）
                max_allowed = len(candidates)
                has_valid = False
                used_indices: set[int] = set()
                for idx_raw in placeholders:
                    if not idx_raw:
                        # `<!--IMAGE:sec_x-->` 不指定索引：视为有效（后续可插入剩余图片）
                        has_valid = True
                        continue
                    try:
                        idx = int(idx_raw)
                    except ValueError:
                        continue
                    if 1 <= idx <= max_allowed:
                        if idx not in used_indices:
                            used_indices.add(idx)
                            has_valid = True
                if not has_valid:
                    invalid_image_placeholders.append(sec_id)

    draft_quality_ok = (
        (total_chars >= MIN_TOTAL_DRAFT_CHARS)
        and (not missing_sections)
        and (not short_sections)
        and (not missing_image_placeholders)
        and (not invalid_image_placeholders)
    )
    sections_to_rewrite = dedupe_preserve_order(
        missing_sections + short_sections + missing_image_placeholders + invalid_image_placeholders
    )

    writer_audit = {
        "total_chars": total_chars,
        "missing_sections": missing_sections,
        "short_sections": short_sections,
        "missing_image_placeholders": missing_image_placeholders,
        "invalid_image_placeholders": invalid_image_placeholders,
        "sections_to_rewrite": sections_to_rewrite,
        "per_section_chars": per_section_chars,
        "thresholds": {
            "min_total_chars": MIN_TOTAL_DRAFT_CHARS,
            "min_core_section_chars": MIN_CORE_SECTION_CHARS,
            "min_normal_section_chars": MIN_NORMAL_SECTION_CHARS,
        },
    }

    rewrite_round = int(state.get("rewrite_round", 0) or 0)
    if not draft_quality_ok:
        rewrite_round += 1

    new_state: ContentState = {
        **state,
        "writer_audit": writer_audit,
        "draft_quality_ok": draft_quality_ok,
        "rewrite_round": rewrite_round,
        "sections_to_rewrite": sections_to_rewrite,
    }
    return _append_step(new_state, "writer_audit")


def writer_router(state: ContentState) -> str:
    if state.get("error"):
        return "next"

    ok = bool(state.get("draft_quality_ok"))
    rewrite_round = int(state.get("rewrite_round", 0) or 0)
    if ok or rewrite_round >= MAX_REWRITE_ROUNDS:
        return "next"
    return "retry"


def merge_sections_node(state: ContentState) -> ContentState:
    if state.get("error"):
        return _append_step(state, "merge_sections_skipped")

    outline = state.get("outline") or {}
    sections = outline.get("sections") if isinstance(outline, dict) else None
    if not isinstance(sections, list):
        sections = []

    title = (state.get("title") or "").strip() or str(outline.get("title") or "").strip() or "未命名文章"
    drafts = state.get("section_drafts") or {}
    if not isinstance(drafts, dict):
        drafts = {}

    merged_parts: List[str] = [f"# {title}".strip()]

    for sec in sections:
        if not isinstance(sec, dict):
            continue
        sec_id = str(sec.get("id") or "").strip()
        sec_title = str(sec.get("title") or "").strip() or sec_id
        level = int(sec.get("level") or 2)
        level = level if level in (2, 3) else 2

        text = drafts.get(sec_id)
        if isinstance(text, str) and text.strip():
            merged_parts.append(text.strip())
            continue

        heading = f"{'##' if level == 2 else '###'} {sec_title}".strip()
        merged_parts.append(heading + "\n\nNO_DATA: 本节内容暂略/资料不足。")

    draft_markdown = "\n\n".join(merged_parts).strip()

    new_state: ContentState = {
        **state,
        "draft_markdown": draft_markdown,
        "refined_markdown": draft_markdown,
        "final_markdown": draft_markdown,
    }
    return _append_step(new_state, "merge_sections")


def reader_review_node(state: ContentState) -> ContentState:
    if state.get("error"):
        return _append_step(state, "reader_review_skipped")

    draft = state.get("draft_markdown") or ""
    try:
        review_comment = reader_review_agent(
            instruction=state.get("instruction", "") or "",
            draft_markdown=draft,
        )
        # 将审阅意见追加到 draft 末尾，作为“审阅附注”供用户参考（或后续流程使用）
        # 也可以仅存入 state 不修改正文。这里选择仅存入 state 并在日志打印，不污染正文。
        new_state: ContentState = {
            **state,
            "reader_review_comment": review_comment,
        }
        if review_comment:
            _LOGGER.info("reader_review_done: %s", review_comment[:200])

        return _append_step(new_state, "reader_review")
    except Exception as exc:  # pragma: no cover
        _LOGGER.error("reader_review_node.failed error=%s", exc)
        return _append_step(state, "reader_review_error")


def doc_refiner_node(state: ContentState) -> ContentState:
    if state.get("error"):
        return _append_step(state, "doc_refiner_skipped")

    settings = get_settings()
    if not bool(getattr(settings, "enable_doc_refiner", True)):
        draft = state.get("draft_markdown") or ""
        new_state: ContentState = {
            **state,
            "refined_markdown": draft,
            "final_markdown": draft,
        }
        return _append_step(new_state, "doc_refiner_disabled")

    draft = state.get("draft_markdown") or ""
    try:
        refined = doc_refiner_agent(outline=state.get("outline") or {}, draft_markdown=draft)
        final_text = refined or draft
        # 添加标题自动编号
        final_text = add_heading_numbers(final_text)
        new_state: ContentState = {
            **state,
            "refined_markdown": final_text,
            "final_markdown": final_text,
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

    updated = illustrator_agent(
        final_markdown=state.get("final_markdown") or state.get("refined_markdown") or state.get("draft_markdown") or "",
        outline=state.get("outline") or {},
        image_metadata=state.get("image_metadata") or {},
    )
    new_state: ContentState = {**state, "final_markdown": updated}
    return _append_step(new_state, "illustrator")


def assembler_node(state: ContentState) -> ContentState:
    # 即使上游出错也尽量落盘，方便排查与兜底返回。
    try:
        title = (state.get("title") or "").strip() or "未命名文章"
        info = assembler_agent(
            article_id=state.get("article_id") or "",
            title=title,
            final_markdown=state.get("final_markdown") or state.get("draft_markdown") or "",
        )
        new_state: ContentState = {
            **state,
            "md_path": info.get("md_path"),
            "md_url": info.get("md_url"),
        }
        return _append_step(new_state, "assembler")
    except Exception as exc:  # pragma: no cover
        _LOGGER.error("assembler_node.failed error=%s", exc)
        new_state = dict(state)
        new_state["error"] = f"assembler_failed: {exc}"
        return _append_step(new_state, "assembler_error")


def summary_for_user_node(state: ContentState) -> ContentState:
    outline = state.get("outline") or {}
    sections = outline.get("sections") if isinstance(outline, dict) else None
    titles: List[str] = []
    if isinstance(sections, list):
        for sec in sections:
            if isinstance(sec, dict) and sec.get("title"):
                titles.append(str(sec["title"]))
    title = (state.get("title") or "").strip() or str(outline.get("title") or "").strip() or "未命名文章"
    md_url = state.get("md_url")

    summary_lines = [f"标题：{title}"]
    if titles:
        summary_lines.append("章节：")
        summary_lines.extend([f"- {t}" for t in titles[:20]])
    if md_url:
        summary_lines.append(f"下载：{md_url}")

    new_state: ContentState = {**state, "summary_for_user": "\n".join(summary_lines).strip()}
    return _append_step(new_state, "summary_for_user")


def get_content_graph():
    graph = StateGraph(ContentState)
    graph.add_node("init", init_node)
    graph.add_node("collector", collector_node)
    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("research_audit", research_audit_node)
    graph.add_node("section_writer", section_writer_node)
    graph.add_node("writer_audit", writer_audit_node)
    graph.add_node("merge_sections", merge_sections_node)
    graph.add_node("reader_review", reader_review_node)
    graph.add_node("doc_refiner", doc_refiner_node)
    graph.add_node("illustrator", illustrator_node)
    graph.add_node("assembler", assembler_node)
    graph.add_node("summary_for_user", summary_for_user_node)

    graph.set_entry_point("init")
    graph.add_edge("init", "collector")
    graph.add_edge("collector", "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "research_audit")
    graph.add_conditional_edges(
        "research_audit",
        research_router,
        {"retry": "researcher", "next": "section_writer"},
    )
    graph.add_edge("section_writer", "writer_audit")
    graph.add_conditional_edges(
        "writer_audit",
        writer_router,
        {"retry": "section_writer", "next": "merge_sections"},
    )
    graph.add_edge("merge_sections", "reader_review")
    graph.add_edge("reader_review", "doc_refiner")
    graph.add_edge("doc_refiner", "illustrator")
    graph.add_edge("illustrator", "assembler")
    graph.add_edge("assembler", "summary_for_user")
    graph.add_edge("summary_for_user", END)

    # 启用 Checkpointer（默认使用内存，生产环境通过 .compile(checkpointer=...) 覆盖）
    return graph.compile(checkpointer=MemorySaver())


__all__ = ["get_content_graph"]
