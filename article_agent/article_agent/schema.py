from __future__ import annotations

import json
from typing import Any, Dict

from pydantic import BaseModel, Field, ValidationError


class PlannerOutput(BaseModel):
    """Planner 子 Agent 的结构化输出。"""

    # 使用 Dict[str, Any] 约束顶层为对象结构，便于 downstream 将各 key 视为稳定的 section_id，
    # 同时避免 Any 带来的复杂 JSON Schema 导致部分 LLM 提示 “invalid JSON schema”。
    outline: Dict[str, Any] = Field(
        ...,
        description="文章大纲结构，按 section_id 聚合的章节定义（如标题、说明等）。",
    )
    sections_to_research: Dict[str, Any] = Field(
        ...,
        description="按 section_id 聚合的研究问题/待补充要点列表，用于驱动后续 Researcher 步骤。",
    )


class ResearcherOutput(BaseModel):
    """Researcher 子 Agent 的结构化输出。"""

    source_summaries: Dict[str, Any] = Field(
        ...,
        description="按 source_id 聚合的来源摘要与原文信息（包含 raw_text、kind、url/path 等字段）。",
    )
    section_notes: Dict[str, Any] = Field(
        ...,
        description="按 section_id 聚合的笔记内容，供 Writer 在写作阶段直接引用与重组。",
    )
    image_metadata: Dict[str, Any] = Field(
        ...,
        description="与图片相关的元数据，例如来源、图片 URL、alt 文本等，用于后续插图步骤。",
    )


class SectionNotesOutput(BaseModel):
    """用于从 LLM 输出中解析 section_notes 字段。"""

    section_notes: Dict[str, Any] = Field(
        ...,
        description="按 section_id 聚合的笔记字典，每个键为小节标识，每个值为该节的长文本笔记。",
    )


def parse_json_output(raw: str, model: type[BaseModel], context: str) -> BaseModel:
    """将 LLM 的字符串输出解析为指定 Pydantic 模型。

    - raw: LLM 输出的原始字符串（期望为 JSON 文本）。
    - model: 目标 Pydantic 模型类型。
    - context: 上下文描述（用于错误信息）。
    """

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} 输出不是合法 JSON：{exc}") from exc

    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"{context} 输出 JSON 结构校验失败：{exc}") from exc


class WriterReviewOutput(BaseModel):
    """Writer 自检结果。"""

    needs_revision: bool = Field(
        ...,
        description="是否需要对当前 Markdown 草稿进行重写或大幅修改。",
    )
    comments: str = Field(
        ...,
        description="针对草稿结构与内容的具体改进建议或说明。",
    )


__all__ = [
    "PlannerOutput",
    "ResearcherOutput",
    "SectionNotesOutput",
    "WriterReviewOutput",
    "parse_json_output",
]
