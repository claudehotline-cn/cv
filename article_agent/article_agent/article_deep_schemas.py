"""Article Deep Agent 结构化输出 Schemas"""

from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


# ============ Collector Output ============
class SourceMaterial(BaseModel):
    """单个素材来源"""
    url: str = Field(description="素材 URL 或文件路径")
    title: str = Field(description="素材标题")
    text_preview: str = Field(max_length=2000, description="文本预览 (前 2000 字符)")
    images: List[Dict[str, str]] = Field(
        default_factory=list,
        description="图片列表，每个包含 {path, alt, vlm_description}"
    )


class CollectorOutput(BaseModel):
    """Collector Agent 输出"""
    sources: List[SourceMaterial] = Field(description="收集到的素材列表")
    overview: str = Field(description="素材概览，供 Planner 使用")
    total_text_chars: int = Field(default=0, description="总文本字符数")
    total_images: int = Field(default=0, description="总图片数")


# ============ Planner Output ============
class Section(BaseModel):
    """文章章节定义"""
    id: str = Field(description="章节 ID，如 sec_1, sec_2")
    title: str = Field(description="章节标题")
    keywords: List[str] = Field(default_factory=list, description="关键词列表")
    target_chars: int = Field(default=800, description="目标字数")
    is_core: bool = Field(default=False, description="是否为核心章节（字数要求更高）")


class OutlineOutput(BaseModel):
    """Planner Agent 输出"""
    title: str = Field(description="文章标题")
    sections: List[Section] = Field(description="章节列表")
    estimated_total_chars: int = Field(description="预估总字数")


# ============ Researcher Output ============
class SectionNotes(BaseModel):
    """章节资料笔记"""
    section_id: str = Field(description="对应的章节 ID")
    notes: str = Field(description="整理后的资料笔记")
    relevant_images: List[Dict[str, str]] = Field(
        default_factory=list,
        description="相关图片列表"
    )


class ResearcherOutput(BaseModel):
    """Researcher Agent 输出"""
    section_notes: List[SectionNotes] = Field(description="各章节的资料笔记")
    source_summaries: Dict[str, str] = Field(
        default_factory=dict,
        description="各来源的摘要"
    )


# ============ Research Audit Output ============
class ResearchAuditResult(BaseModel):
    """Research Audit 结果（规则质检）"""
    section_id: str
    has_notes: bool = Field(description="是否有资料笔记")
    notes_char_count: int = Field(description="笔记字符数")
    is_sufficient: bool = Field(description="资料是否充足")
    issues: List[str] = Field(default_factory=list, description="问题列表")


class ResearchAuditOutput(BaseModel):
    """Research Audit 总输出"""
    results: List[ResearchAuditResult]
    all_passed: bool = Field(description="是否全部通过")
    sections_to_reresearch: List[str] = Field(
        default_factory=list,
        description="需要重新研究的章节 ID"
    )


# ============ Writer Output ============
class SectionDraft(BaseModel):
    """章节草稿"""
    section_id: str = Field(description="章节 ID")
    title: str = Field(description="章节标题")
    markdown: str = Field(description="Markdown 内容")
    char_count: int = Field(description="字符数")


class WriterOutput(BaseModel):
    """Writer Agent 输出"""
    drafts: List[SectionDraft] = Field(description="各章节草稿")
    total_char_count: int = Field(default=0, description="总字数")


# ============ Writer Audit Output ============
class WriterAuditResult(BaseModel):
    """Writer Audit 结果（规则质检）"""
    section_id: str
    char_count: int = Field(description="章节字符数")
    min_required: int = Field(description="最低要求字数")
    is_sufficient: bool = Field(description="字数是否达标")
    has_heading: bool = Field(description="是否有标题")
    issues: List[str] = Field(default_factory=list, description="问题列表")


class WriterAuditOutput(BaseModel):
    """Writer Audit 总输出"""
    results: List[WriterAuditResult]
    all_passed: bool = Field(description="是否全部通过")
    sections_to_rewrite: List[str] = Field(
        default_factory=list,
        description="需要重写的章节 ID"
    )


# ============ Reviewer Output ============
class ReviewFeedback(BaseModel):
    """章节审阅反馈"""
    section_id: str
    quality_score: int = Field(ge=1, le=10, description="质量评分 1-10")
    issues: List[str] = Field(default_factory=list, description="问题列表")
    suggestions: List[str] = Field(default_factory=list, description="改进建议")


class ReviewerOutput(BaseModel):
    """Reviewer Agent 输出"""
    overall_quality: int = Field(ge=1, le=10, description="整体质量评分")
    section_feedback: List[ReviewFeedback] = Field(description="各章节反馈")
    sections_to_rewrite: List[str] = Field(
        default_factory=list,
        description="需要重写的章节 ID"
    )
    approved: bool = Field(default=False, description="是否通过审阅")


# ============ Illustrator Output ============
class ImagePlacement(BaseModel):
    """图片放置位置"""
    image_url: str = Field(description="图片 URL")
    alt_text: str = Field(description="图片替代文本")
    after_heading: str = Field(description="放置在哪个标题后，如 '## 1.1 背景介绍'")
    caption: str = Field(description="图片说明")


class IllustratorOutput(BaseModel):
    """Illustrator Agent 输出"""
    placements: List[ImagePlacement] = Field(description="图片放置列表")
    final_markdown: str = Field(description="插入图片后的完整 Markdown")


# ============ Assembler Output ============
class AssemblerOutput(BaseModel):
    """Assembler Agent 输出"""
    article_id: str = Field(description="文章 ID")
    md_path: str = Field(description="Markdown 文件本地路径")
    md_url: str = Field(description="Markdown 文件可访问 URL")
    article_content: Optional[str] = Field(default=None, description="文章完整内容")


# ============ Main Agent Output ============
class ArticleAgentOutput(BaseModel):
    """Article Deep Agent 最终输出"""
    status: str = Field(description="状态: 'success' 或 'error'")
    title: str = Field(description="文章标题")
    md_path: str = Field(description="Markdown 文件本地路径")
    md_url: str = Field(description="Markdown 文件可访问 URL")
    summary: str = Field(description="文章摘要")
    word_count: int = Field(description="总字数")
    article_content: Optional[str] = Field(default=None, description="完整的文章 Markdown 内容")
    error_message: Optional[str] = Field(default=None, description="错误信息（如有）")


__all__ = [
    "SourceMaterial",
    "CollectorOutput",
    "Section",
    "OutlineOutput",
    "SectionNotes",
    "ResearcherOutput",
    "ResearchAuditResult",
    "ResearchAuditOutput",
    "SectionDraft",
    "WriterOutput",
    "WriterAuditResult",
    "WriterAuditOutput",
    "ReviewFeedback",
    "ReviewerOutput",
    "ImagePlacement",
    "IllustratorOutput",
    "AssemblerOutput",
    "ArticleAgentOutput",
]
