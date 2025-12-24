from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class ContentState(TypedDict, total=False):
    """内容整理 Graph 的共享状态结构（尽量保持 JSON 可序列化）。"""

    # 用户输入
    instruction: str
    urls: List[str]
    file_paths: List[str]
    article_id: str
    title: Optional[str]

    # 采集 & 规划
    # sources: source_id -> {"kind": "url"/"file", "url"/"path": ..., "title": ..., "text": ..., "images": [...]}
    sources: Dict[str, Any]
    rough_sources_overview: Dict[str, Any]
    outline: Dict[str, Any]  # 符合 OutlineOutput 的 dict：{"title": str, "sections": [...]}
    sections_to_research: List[str]  # section_id 列表

    # 研究结果
    section_notes: Dict[str, str]  # section_id -> 原文笔记（允许 NO_DATA 占位）
    image_metadata: Dict[str, List[Dict[str, Any]]]  # section_id -> 图片列表
    source_summaries: Dict[str, str]  # source_id -> 概述
    research_error: Optional[str]
    research_missing_all: List[str]
    research_missing_important: List[str]
    research_weak_important: List[str]
    research_extra_keys: List[str]
    research_ok: bool
    research_round: int

    # 写作 & 审核
    section_drafts: Dict[str, str]  # section_id -> 该节草稿
    draft_markdown: str  # merge 后的粗稿
    refined_markdown: str  # doc_refiner 结果（可选）
    final_markdown: str  # 最终文稿
    writer_audit: Dict[str, Any]
    draft_quality_ok: bool
    rewrite_round: int
    sections_to_rewrite: List[str]

    # 导出
    md_path: Optional[str]
    md_url: Optional[str]
    summary_for_user: Optional[str]

    # 控制流 / 日志
    error: Optional[str]
    step_history: List[str]
    step_events: List[Dict[str, Any]]  # 前端流式展示的事件列表
    reader_review_comment: Optional[str]


__all__ = ["ContentState"]
