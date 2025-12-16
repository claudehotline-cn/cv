from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError


class OutlineSection(BaseModel):
    """文章大纲的单个小节定义。"""

    id: str = Field(
        ...,
        description='小写字母 + 下划线组成的唯一字符串，例如 "sec_intro"。',
    )
    title: str = Field(..., description="该节标题，简洁易懂。")
    level: int = Field(..., description="Markdown 标题级别：2 表示 ##，3 表示 ###。")
    parent_id: Optional[str] = Field(
        default=None,
        description="可选。若 level=3，则指向所属二级标题的 id。",
    )
    is_core: bool = Field(default=False, description="是否为文章核心内容部分。")
    target_word_count: int = Field(
        default=500,
        description="该小节的目标字数。由 Planner 根据用户总字数要求计算分配。",
    )


class OutlineOutput(BaseModel):
    """Planner 子 Agent 的结构化输出。"""

    title: str = Field(..., description="文章总标题。")
    sections: List[OutlineSection] = Field(..., description="按文章顺序排列的章节列表。")
    writing_style: str = Field(
        default="",
        description="针对本文的写作风格指导（语气、受众、用词规范等），供 Writer 参考。",
    )
    sections_to_research: List[str] = Field(
        default_factory=list,
        description="需要 Researcher 重点研究的 section_id 列表。",
    )


class ResearcherOutput(BaseModel):
    """Researcher 子 Agent 的结构化输出。"""

    section_notes: Dict[str, str] = Field(
        ...,
        description="section_id -> 该节原文素材笔记（允许 NO_DATA 占位）。",
    )
    image_metadata: Dict[str, List[Dict[str, Any]]] = Field(
        ...,
        description="section_id -> 可用图片列表（只来自原文）。",
    )
    source_summaries: Dict[str, str] = Field(
        ...,
        description="source_id -> 该来源的 1-3 段总结。",
    )


class ImageSelectionOutput(BaseModel):
    """用于在图片缺失时，二次让 LLM 仅选择图片并输出 image_metadata。"""

    image_metadata: Dict[str, List[Dict[str, Any]]] = Field(
        ...,
        description="section_id -> 可用图片列表（只来自 sources.images）。",
    )


class ImageInsertion(BaseModel):
    """单个图片插入指令。"""
    
    image_index: int = Field(..., description="图片在候选列表中的索引（1-based）。")
    target_heading: str = Field(..., description="目标章节的完整标题（如 '## 2. 自注意力机制'）。")
    insert_after_text: str = Field(
        default="",
        description="图片应该插入在哪段文字之后。提供该段落的前20-30个字作为定位依据。空字符串表示插入在该章节开头。",
    )
    reason: str = Field(default="", description="匹配原因说明。")


class ImageInsertionPlan(BaseModel):
    """Illustrator Agent 的输出：图片插入计划。"""
    
    insertions: List[ImageInsertion] = Field(
        default_factory=list,
        description="图片插入列表，每个元素指定一张图片应该插入到哪个章节。",
    )


class SectionDraftOutput(BaseModel):
    """Section Writer 子 Agent 的结构化输出。"""

    section_id: str = Field(..., description="与输入完全相同的 section_id。")
    markdown: str = Field(..., description="从本节标题开始的 Markdown 内容。")


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


class WriterAuditOutput(BaseModel):
    """Writer Audit（可选 LLM）结构化输出。"""

    total_chars: int = Field(..., description="整篇文章的字符数（整数）。")
    short_sections: List[str] = Field(default_factory=list, description="长度偏短的 section_id 列表。")
    missing_sections: List[str] = Field(default_factory=list, description="缺失章节 section_id 列表。")
    low_density_sections: List[str] = Field(default_factory=list, description="信息密度偏低的 section_id 列表。")
    off_topic_sections: List[str] = Field(default_factory=list, description="偏离主题的 section_id 列表。")
    logic_issues: List[Dict[str, str]] = Field(
        default_factory=list,
        description='逻辑问题列表，例如 {"section_id": "...", "issue": "..."}。',
    )
    style_issues: List[str] = Field(default_factory=list, description="文风/可读性问题列表。")
    quality_ok: bool = Field(..., description="是否达到可对外发布的初稿水平。")


__all__ = [
    "OutlineSection",
    "OutlineOutput",
    "ResearcherOutput",
    "ImageSelectionOutput",
    "ImageInsertion",
    "ImageInsertionPlan",
    "SectionDraftOutput",
    "WriterAuditOutput",
    "parse_json_output",
]
