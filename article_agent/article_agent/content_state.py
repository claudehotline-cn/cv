from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class ContentState(TypedDict, total=False):
    """内容整理 Graph 的共享状态结构。"""

    # 用户输入
    instruction: str
    urls: List[str]
    file_paths: List[str]
    article_id: str
    title: str

    # 轻量 Researcher / Collector 输出
    rough_sources_overview: Any

    # Planner 输出
    outline: Any
    sections_to_research: Any

    # Researcher 输出
    source_summaries: Any
    section_notes: Any
    image_metadata: Any

    # Section Writer / Writer 输出
    section_drafts: Optional[Dict[str, str]]
    draft_markdown: Optional[str]
    refined_markdown: Optional[str]
    draft_quality_ok: Optional[bool]
    refine_round: int

    # Illustrator 输出
    final_markdown: Optional[str]
    illustrator_skip_reason: Optional[str]

    # Assembler 输出
    download_info: Optional[Dict[str, str]]

    # Writer 自检
    writer_review: Optional[str]
    writer_needs_revision: Optional[bool]
    writer_attempts: int

    # Researcher 控制
    researcher_attempts: int

    # 控制流 / 日志
    error: Optional[str]
    step_history: List[str]


__all__ = ["ContentState"]
