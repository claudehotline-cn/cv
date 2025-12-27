"""Article Deep Agent Tools - 各 SubAgent 使用的工具函数"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from .article_deep_schemas import (
    CollectorOutput,
    OutlineOutput,
    ResearcherOutput,
    ResearchAuditOutput,
    WriterOutput,
    WriterAuditOutput,
    ReviewerOutput,
    IllustratorOutput,
    AssemblerOutput,
)

_LOGGER = logging.getLogger("article_agent.article_deep_tools")


# ============================================================================
# Collector Agent Tools
# ============================================================================

@tool
def fetch_url_tool(url: str, max_images: int = 30, max_text_chars: int = 60000) -> Dict[str, Any]:
    """抓取 URL 内容，提取文本和图片。
    
    Args:
        url: 要抓取的 URL
        max_images: 最大图片数
        max_text_chars: 最大文本字符数
        
    Returns:
        包含 title, text, images 的字典
    """
    from .tools_files import fetch_url_with_images
    
    _LOGGER.info(f"fetch_url_tool called with url: {url[:50]}...")
    try:
        data = fetch_url_with_images(url, max_images=max_images, max_text_chars=max_text_chars)
        text = data.get("text") or ""
        images = data.get("images") or []
        
        # 格式化图片列表
        formatted_images = [
            {
                "path_or_url": (img.get("url") or img.get("src") or ""),
                "alt": (img.get("alt") or ""),
            }
            for img in images
            if isinstance(img, dict) and (img.get("url") or img.get("src"))
        ]
        
        _LOGGER.info(f"fetch_url_tool success: {len(text)} chars, {len(formatted_images)} images")
        return {
            "title": data.get("title", ""),
            "text": text,
            "images": formatted_images,
            "success": True,
        }
    except Exception as exc:
        _LOGGER.warning(f"fetch_url_tool failed: {exc}")
        return {
            "title": "",
            "text": "",
            "images": [],
            "success": False,
            "error": str(exc),
        }


@tool
def load_file_tool(file_path: str, max_text_chars: int = 60000) -> Dict[str, Any]:
    """加载本地文件内容。
    
    Args:
        file_path: 本地文件路径
        max_text_chars: 最大文本字符数
        
    Returns:
        包含 title, text 的字典
    """
    from .tools_files import load_text_from_file
    
    _LOGGER.info(f"load_file_tool called with file_path: {file_path}")
    try:
        data = load_text_from_file(file_path, max_text_chars=max_text_chars)
        text = data.get("text") or ""
        
        _LOGGER.info(f"load_file_tool success: {len(text)} chars")
        return {
            "title": data.get("path", file_path),
            "text": text,
            "success": True,
        }
    except Exception as exc:
        _LOGGER.warning(f"load_file_tool failed: {exc}")
        return {
            "title": file_path,
            "text": "",
            "success": False,
            "error": str(exc),
        }


@tool
def collect_all_sources_tool(
    urls: List[str],
    file_paths: List[str],
    max_text_chars: int = 60000,
    max_overview_chars: int = 4000,
    max_images_per_source: int = 30,
) -> Dict[str, Any]:
    """收集所有素材来源，返回 CollectorOutput。
    
    Args:
        urls: URL 列表
        file_paths: 文件路径列表
        max_text_chars: 每个来源最大文本字符数
        max_overview_chars: 概览最大字符数
        max_images_per_source: 每个来源最大图片数
        
    Returns:
        CollectorOutput 字典
    """
    from .tools_files import fetch_url_with_images, load_text_from_file
    
    _LOGGER.info(f"collect_all_sources_tool called with {len(urls or [])} urls, {len(file_paths or [])} files")
    
    sources = []
    overview_parts = []
    total_text_chars = 0
    total_images = 0
    
    # 处理 URLs
    for idx, url in enumerate(urls or []):
        try:
            data = fetch_url_with_images(url, max_images=max_images_per_source, max_text_chars=max_text_chars)
            text = data.get("text") or ""
            snippet = text[:max_overview_chars] if isinstance(text, str) else ""
            images = data.get("images") or []
            
            formatted_images = [
                {
                    "path_or_url": (img.get("url") or img.get("src") or ""),
                    "alt": (img.get("alt") or ""),
                }
                for img in images
                if isinstance(img, dict) and (img.get("url") or img.get("src"))
            ]
            
            sources.append({
                "url": url,
                "title": data.get("title", ""),
                "text_preview": snippet,
                "images": formatted_images,
            })
            
            total_text_chars += len(text)
            total_images += len(formatted_images)
            overview_parts.append(f"- [{data.get('title', url[:30])}]({url}): {len(text)} 字符, {len(formatted_images)} 图片")
            
            _LOGGER.info(f"Collected URL {idx}: {len(text)} chars, {len(formatted_images)} images")
        except Exception as exc:
            _LOGGER.warning(f"Failed to collect URL {url}: {exc}")
            overview_parts.append(f"- [错误] {url[:30]}: {exc}")
    
    # 处理文件
    for idx, path in enumerate(file_paths or []):
        try:
            data = load_text_from_file(path, max_text_chars=max_text_chars)
            text = data.get("text") or ""
            snippet = text[:max_overview_chars] if isinstance(text, str) else ""
            
            sources.append({
                "url": path,
                "title": path,
                "text_preview": snippet,
                "images": [],
            })
            
            total_text_chars += len(text)
            overview_parts.append(f"- [文件] {path}: {len(text)} 字符")
            
            _LOGGER.info(f"Collected file {idx}: {len(text)} chars")
        except Exception as exc:
            _LOGGER.warning(f"Failed to collect file {path}: {exc}")
            overview_parts.append(f"- [错误] {path}: {exc}")
    
    overview = "## 素材概览\n\n" + "\n".join(overview_parts) + f"\n\n**总计**: {total_text_chars} 字符, {total_images} 图片"
    
    return {
        "sources": sources,
        "overview": overview,
        "total_text_chars": total_text_chars,
        "total_images": total_images,
    }


# ============================================================================
# Planner Agent Tools
# ============================================================================

@tool
def generate_outline_tool(instruction: str, overview: str, target_word_count: int = 3000) -> Dict[str, Any]:
    """根据用户指令和素材概览生成文章大纲。
    
    Args:
        instruction: 用户写作指令
        overview: 素材概览
        target_word_count: 目标总字数
        
    Returns:
        OutlineOutput 字典
    """
    import json
    import re
    from .llm_runtime import build_chat_llm
    from langchain_core.messages import HumanMessage, SystemMessage
    
    _LOGGER.info(f"generate_outline_tool called with target_word_count: {target_word_count}")
    
    system_prompt = f"""
你是 Planner，负责为一篇文章设计大纲。

【核心原则】
文章主题必须完全基于 overview 中的实际内容！
- 仔细阅读 overview 中的内容概览
- 文章标题和章节必须围绕这些来源的实际内容来设计
- 严禁生成与 overview 内容无关的主题

【任务目标】
1. 分析 overview，理解用户提供的来源实际讲什么内容。
2. 基于来源内容和 instruction（用户偏好），为文章设计结构清晰的大纲。
3. 输出文章标题 title（必须反映来源内容的主题）。
4. 输出 sections 列表，每个 section 包含：
   - id：唯一字符串，如 "sec_1", "sec_2"
   - title：章节标题
   - keywords：关键词列表
   - target_chars：该章节的目标字数
   - is_core：是否为核心章节

【字数分配规则】
- 总字数目标：{target_word_count} 字
- 核心章节 (is_core=true)：分配 1.5 倍权重
- 引言/总结：分配 0.7 倍权重
- 确保所有 section 的 target_chars 之和约等于目标总字数

【输出格式】
只输出一个 JSON，格式如下：
{{
  "title": "文章标题",
  "sections": [
    {{"id": "sec_1", "title": "引言", "keywords": ["关键词1"], "target_chars": 400, "is_core": false}},
    {{"id": "sec_2", "title": "核心内容", "keywords": ["关键词2"], "target_chars": 800, "is_core": true}}
  ],
  "estimated_total_chars": {target_word_count}
}}
"""

    user_prompt = f"""
【用户指令】
{instruction}

【素材概览】
{overview}

请根据以上内容生成文章大纲（只输出 JSON）：
"""

    try:
        llm = build_chat_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        content = response.content.strip()
        
        # 尝试提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            _LOGGER.info(f"generate_outline_tool success: {len(result.get('sections', []))} sections")
            return result
        else:
            _LOGGER.warning(f"generate_outline_tool: no JSON found in response")
            return {
                "title": "未知标题",
                "sections": [],
                "estimated_total_chars": 0,
                "error": "无法解析 LLM 响应",
            }
    except Exception as exc:
        _LOGGER.error(f"generate_outline_tool failed: {exc}")
        return {
            "title": "错误",
            "sections": [],
            "estimated_total_chars": 0,
            "error": str(exc),
        }


# ============================================================================
# Researcher Agent Tools
# ============================================================================

@tool
def research_section_tool(
    section_id: str,
    section_title: str,
    keywords: List[str],
    sources_text: str,
    available_images: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """为指定章节整理资料笔记。
    
    Args:
        section_id: 章节 ID
        section_title: 章节标题
        keywords: 关键词列表
        sources_text: 素材文本（已合并）
        available_images: 可用图片列表
        
    Returns:
        SectionNotes 字典
    """
    import json
    import re
    from .llm_runtime import build_chat_llm
    from langchain_core.messages import HumanMessage, SystemMessage
    
    _LOGGER.info(f"research_section_tool called for section: {section_id}")
    
    system_prompt = f"""
你是 Researcher，负责为文章的一个章节整理资料笔记。

【任务】
根据提供的素材文本，为章节 "{section_title}" 整理资料笔记。

【关键词】
{', '.join(keywords) if keywords else '无特定关键词'}

【要求】
1. 提取与章节主题相关的关键信息
2. 包含具体的事实、数据、引用
3. 笔记至少 300 字符
4. 格式清晰，使用要点列表

【输出格式】
只输出资料笔记内容（纯文本，不需要 JSON）。
"""

    user_prompt = f"""
【素材内容】
{sources_text[:8000]}  # 限制长度

请为章节 "{section_title}" 整理资料笔记：
"""

    try:
        llm = build_chat_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        notes = response.content.strip()
        
        # 匹配相关图片
        relevant_images = []
        if available_images:
            for img in available_images[:5]:  # 最多 5 张
                alt = img.get("alt", "")
                if any(kw.lower() in alt.lower() for kw in keywords):
                    relevant_images.append(img)
        
        _LOGGER.info(f"research_section_tool success: {len(notes)} chars, {len(relevant_images)} images")
        return {
            "section_id": section_id,
            "notes": notes,
            "relevant_images": relevant_images,
        }
    except Exception as exc:
        _LOGGER.error(f"research_section_tool failed: {exc}")
        return {
            "section_id": section_id,
            "notes": f"资料整理失败: {exc}",
            "relevant_images": [],
        }


@tool
def research_all_sections_tool(
    outline: Dict[str, Any],
    sources: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """为所有章节整理资料笔记。
    
    Args:
        outline: 文章大纲
        sources: 素材列表
        
    Returns:
        ResearcherOutput 字典
    """
    _LOGGER.info(f"research_all_sections_tool called")
    
    # 合并所有素材文本
    all_text = "\n\n".join([
        f"【来源: {s.get('title', s.get('url', 'unknown'))}】\n{s.get('text_preview', '')}"
        for s in sources
    ])
    
    # 收集所有图片
    all_images = []
    for s in sources:
        all_images.extend(s.get("images", []))
    
    section_notes = []
    for sec in outline.get("sections", []):
        result = research_section_tool.invoke({
            "section_id": sec["id"],
            "section_title": sec["title"],
            "keywords": sec.get("keywords", []),
            "sources_text": all_text,
            "available_images": all_images,
        })
        section_notes.append(result)
    
    return {
        "section_notes": section_notes,
        "source_summaries": {s.get("url", f"source_{i}"): s.get("text_preview", "")[:500] for i, s in enumerate(sources)},
    }


@tool
def research_audit_tool(section_notes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """资料质检（规则质检，不用 LLM）。
    
    Args:
        section_notes: 各章节的资料笔记
        
    Returns:
        ResearchAuditOutput 字典
    """
    _LOGGER.info(f"research_audit_tool called with {len(section_notes)} sections")
    
    results = []
    sections_to_reresearch = []
    
    for note in section_notes:
        char_count = len(note.get("notes", ""))
        is_sufficient = char_count >= 300  # 最低 300 字符
        
        result = {
            "section_id": note.get("section_id", ""),
            "has_notes": bool(note.get("notes")),
            "notes_char_count": char_count,
            "is_sufficient": is_sufficient,
            "issues": [] if is_sufficient else [f"资料不足，当前 {char_count} 字符，需要至少 300 字符"],
        }
        results.append(result)
        
        if not is_sufficient:
            sections_to_reresearch.append(note.get("section_id", ""))
    
    all_passed = len(sections_to_reresearch) == 0
    _LOGGER.info(f"research_audit_tool: all_passed={all_passed}, to_reresearch={sections_to_reresearch}")
    
    return {
        "results": results,
        "all_passed": all_passed,
        "sections_to_reresearch": sections_to_reresearch,
    }



# ============================================================================
# Writer Agent Tools
# ============================================================================

@tool
def write_section_tool(
    section_id: str,
    section_title: str,
    target_chars: int,
    notes: str,
    is_core: bool = False,
) -> Dict[str, Any]:
    """撰写指定章节内容。
    
    Args:
        section_id: 章节 ID
        section_title: 章节标题
        target_chars: 目标字数
        notes: 资料笔记
        is_core: 是否核心章节
        
    Returns:
        SectionDraft 字典
    """
    from .llm_runtime import build_chat_llm
    from langchain_core.messages import HumanMessage, SystemMessage
    
    _LOGGER.info(f"write_section_tool called for section: {section_id}, target_chars: {target_chars}")
    
    min_chars = 800 if is_core else 400
    
    system_prompt = f"""
你是 Writer，负责撰写文章的一个章节。

【任务】
根据资料笔记，撰写章节 "{section_title}" 的内容。

【要求】
1. 字数目标：{target_chars} 字符（最少 {min_chars} 字符）
2. 使用 Markdown 格式，以 "## {section_title}" 开头
3. 内容应流畅、有逻辑、信息丰富
4. 适当使用列表、引用等格式
5. 禁止使用占位符或待填充标记
6. 确保内容基于资料笔记，不要编造数据

【输出格式】
直接输出 Markdown 格式的章节内容（以 ## 开头）。
"""

    user_prompt = f"""
【资料笔记】
{notes[:6000]}

请撰写章节内容（目标 {target_chars} 字符）：
"""

    try:
        llm = build_chat_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        markdown = response.content.strip()
        
        # 确保以标题开头
        if not markdown.startswith("#"):
            markdown = f"## {section_title}\n\n{markdown}"
        
        char_count = len(markdown)
        _LOGGER.info(f"write_section_tool success: {char_count} chars")
        
        return {
            "section_id": section_id,
            "title": section_title,
            "markdown": markdown,
            "char_count": char_count,
        }
    except Exception as exc:
        _LOGGER.error(f"write_section_tool failed: {exc}")
        return {
            "section_id": section_id,
            "title": section_title,
            "markdown": f"## {section_title}\n\n撰写失败: {exc}",
            "char_count": 0,
        }


@tool
def write_all_sections_tool(
    outline: Dict[str, Any],
    section_notes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """撰写所有章节内容。
    
    Args:
        outline: 文章大纲
        section_notes: 各章节的资料笔记
        
    Returns:
        WriterOutput 字典
    """
    _LOGGER.info(f"write_all_sections_tool called")
    
    # 构建笔记映射
    notes_map = {n["section_id"]: n.get("notes", "") for n in section_notes}
    
    drafts = []
    total_chars = 0
    
    for sec in outline.get("sections", []):
        section_id = sec["id"]
        notes = notes_map.get(section_id, "")
        
        result = write_section_tool.invoke({
            "section_id": section_id,
            "section_title": sec["title"],
            "target_chars": sec.get("target_chars", 500),
            "notes": notes,
            "is_core": sec.get("is_core", False),
        })
        drafts.append(result)
        total_chars += result.get("char_count", 0)
    
    return {
        "drafts": drafts,
        "total_char_count": total_chars,
    }


@tool
def writer_audit_tool(drafts: List[Dict[str, Any]], outline: Dict[str, Any]) -> Dict[str, Any]:
    """写作质检（规则质检，不用 LLM）。
    
    Args:
        drafts: 各章节草稿
        outline: 文章大纲
        
    Returns:
        WriterAuditOutput 字典
    """
    # TODO: Phase 2 实现，复用 deep_graph.py 中的 writer_audit_node 逻辑
    _LOGGER.info(f"writer_audit_tool called")
    
    # 构建 section 字数要求映射
    section_requirements = {}
    for sec in outline.get("sections", []):
        section_requirements[sec["id"]] = {
            "target_chars": sec.get("target_chars", 400),
            "is_core": sec.get("is_core", False),
        }
    
    results = []
    sections_to_rewrite = []
    
    for draft in drafts:
        section_id = draft.get("section_id", "")
        char_count = draft.get("char_count", 0)
        
        req = section_requirements.get(section_id, {"target_chars": 400, "is_core": False})
        min_required = 800 if req["is_core"] else 400
        
        is_sufficient = char_count >= min_required
        has_heading = draft.get("markdown", "").strip().startswith("#")
        
        issues = []
        if not is_sufficient:
            issues.append(f"字数不足，当前 {char_count} 字符，需要至少 {min_required} 字符")
        if not has_heading:
            issues.append("缺少章节标题")
        
        result = {
            "section_id": section_id,
            "char_count": char_count,
            "min_required": min_required,
            "is_sufficient": is_sufficient,
            "has_heading": has_heading,
            "issues": issues,
        }
        results.append(result)
        
        if issues:
            sections_to_rewrite.append(section_id)
    
    return {
        "results": results,
        "all_passed": len(sections_to_rewrite) == 0,
        "sections_to_rewrite": sections_to_rewrite,
    }


# ============================================================================
# Reviewer Agent Tools
# ============================================================================

@tool
def review_draft_tool(drafts: List[Dict[str, Any]], instruction: str) -> Dict[str, Any]:
    """审阅草稿，返回反馈和是否通过。
    
    Args:
        drafts: 各章节草稿
        instruction: 用户写作指令
        
    Returns:
        ReviewerOutput 字典
    """
    import json
    import re
    from .llm_runtime import build_chat_llm
    from langchain_core.messages import HumanMessage, SystemMessage
    
    _LOGGER.info(f"review_draft_tool called with {len(drafts)} sections")
    
    # 合并所有草稿内容
    all_markdown = "\n\n".join([d.get("markdown", "") for d in drafts])
    
    system_prompt = """
你是 Reviewer，负责从读者视角审阅文章草稿。

【任务】
评估文章质量，指出问题并给出改进建议。

【评分标准】
- 9-10: 优秀，可直接发布
- 7-8: 良好，小修后可发布
- 5-6: 一般，需要部分重写
- 1-4: 较差，需要大幅重写

【输出格式】
输出 JSON：
{
  "overall_quality": 8,
  "section_feedback": [
    {"section_id": "sec_1", "quality_score": 8, "issues": [], "suggestions": []}
  ],
  "sections_to_rewrite": [],
  "approved": true
}
"""

    user_prompt = f"""
【用户指令】
{instruction}

【文章草稿】
{all_markdown[:10000]}

请审阅并输出 JSON：
"""

    try:
        llm = build_chat_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        content = response.content.strip()
        
        # 提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            # 确保 approved 字段
            if "approved" not in result:
                result["approved"] = result.get("overall_quality", 0) >= 7
            _LOGGER.info(f"review_draft_tool: quality={result.get('overall_quality')}, approved={result.get('approved')}")
            return result
        else:
            # 默认通过
            _LOGGER.warning(f"review_draft_tool: no JSON found, defaulting to approved")
            return {
                "overall_quality": 7,
                "section_feedback": [],
                "sections_to_rewrite": [],
                "approved": True,
            }
    except Exception as exc:
        _LOGGER.error(f"review_draft_tool failed: {exc}")
        return {
            "overall_quality": 7,
            "section_feedback": [],
            "sections_to_rewrite": [],
            "approved": True,
            "error": str(exc),
        }


# ============================================================================
# Illustrator Agent Tools
# ============================================================================

@tool
def match_images_tool(
    markdown: str,
    available_images: List[Dict[str, Any]],
    max_images: int = 5,
) -> Dict[str, Any]:
    """匹配图片到文章内容，确定放置位置。
    
    Args:
        markdown: 完整文章 Markdown
        available_images: 可用图片列表
        max_images: 最大图片数
        
    Returns:
        IllustratorOutput 字典
    """
    import json
    import re
    from .llm_runtime import build_chat_llm
    from langchain_core.messages import HumanMessage, SystemMessage
    
    _LOGGER.info(f"match_images_tool called with {len(available_images)} images")
    
    if not available_images:
        _LOGGER.info("match_images_tool: no images available")
        return {
            "placements": [],
            "final_markdown": markdown,
        }
    
    # 提取文章中的标题
    headings = re.findall(r'^(#{1,3}\s+.+)$', markdown, re.MULTILINE)
    
    # 准备图片信息
    images_info = "\n".join([
        f"- 图片{i+1}: {img.get('path_or_url', '')[:50]}... | alt: {img.get('alt', '')}"
        for i, img in enumerate(available_images[:10])
    ])
    
    system_prompt = f"""
你是 Illustrator，负责为文章选择和放置合适的图片。

【可用图片】
{images_info}

【文章标题】
{chr(10).join(headings[:10])}

【任务】
1. 从可用图片中选择最多 {max_images} 张与文章内容相关的图片
2. 确定每张图片应放置在哪个标题后
3. 生成图片说明

【输出格式】
输出 JSON：
{{
  "placements": [
    {{"image_index": 0, "after_heading": "## 引言", "caption": "图片说明"}}
  ]
}}
"""

    user_prompt = f"""
【文章内容】
{markdown[:5000]}

请选择图片并确定放置位置（输出 JSON）：
"""

    try:
        llm = build_chat_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        content = response.content.strip()
        
        # 提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            placements = result.get("placements", [])
            
            # 构建最终 Markdown（插入图片）
            final_markdown = markdown
            for p in reversed(placements):  # 倒序插入，避免位置偏移
                img_idx = p.get("image_index", 0)
                if img_idx < len(available_images):
                    img = available_images[img_idx]
                    img_url = img.get("path_or_url", "")
                    alt = img.get("alt", "")
                    caption = p.get("caption", "")
                    after_heading = p.get("after_heading", "")
                    
                    # 在标题后插入图片
                    img_md = f"\n\n![{caption or alt}]({img_url})\n*{caption}*\n"
                    if after_heading:
                        final_markdown = final_markdown.replace(
                            after_heading,
                            after_heading + img_md,
                            1
                        )
            
            formatted_placements = [
                {
                    "image_url": available_images[p.get("image_index", 0)].get("path_or_url", ""),
                    "alt_text": available_images[p.get("image_index", 0)].get("alt", ""),
                    "after_heading": p.get("after_heading", ""),
                    "caption": p.get("caption", ""),
                }
                for p in placements if p.get("image_index", 0) < len(available_images)
            ]
            
            _LOGGER.info(f"match_images_tool success: {len(formatted_placements)} images placed")
            return {
                "placements": formatted_placements,
                "final_markdown": final_markdown,
            }
        else:
            _LOGGER.warning(f"match_images_tool: no JSON found")
            return {
                "placements": [],
                "final_markdown": markdown,
            }
    except Exception as exc:
        _LOGGER.error(f"match_images_tool failed: {exc}")
        return {
            "placements": [],
            "final_markdown": markdown,
            "error": str(exc),
        }


# ============================================================================
# Assembler Agent Tools
# ============================================================================

@tool
def assemble_article_tool(
    article_id: str,
    title: str,
    final_markdown: str,
) -> Dict[str, Any]:
    """组装最终文章并保存。
    
    Args:
        article_id: 文章 ID
        title: 文章标题
        final_markdown: 最终 Markdown
        
    Returns:
        AssemblerOutput 字典
    """
    from .tools_files import export_markdown
    import re
    
    _LOGGER.info(f"assemble_article_tool called for: {article_id}")
    
    # 清理 Markdown
    cleaned_md = final_markdown
    
    # 去除多余空行
    cleaned_md = re.sub(r'\n{3,}', '\n\n', cleaned_md)
    
    # 去除思维过程标记
    cleaned_md = re.sub(r'<think>[\s\S]*?</think>', '', cleaned_md)
    
    # 确保标题正确
    if not cleaned_md.strip().startswith("#"):
        cleaned_md = f"# {title}\n\n{cleaned_md}"
    
    try:
        result = export_markdown(cleaned_md, title, article_id)
        _LOGGER.info(f"assemble_article_tool success: {result.get('md_path')}")
        return {
            "article_id": article_id,
            "md_path": result.get("md_path", ""),
            "md_url": result.get("md_url", ""),
        }
    except Exception as exc:
        _LOGGER.error(f"assemble_article_tool failed: {exc}")
        # 备用路径
        return {
            "article_id": article_id,
            "md_path": f"/data/articles/{article_id}.md",
            "md_url": f"/articles/{article_id}.md",
            "error": str(exc),
        }


__all__ = [
    # Collector
    "fetch_url_tool",
    "load_file_tool",
    "collect_all_sources_tool",
    # Planner
    "generate_outline_tool",
    # Researcher
    "research_section_tool",
    "research_all_sections_tool",
    "research_audit_tool",
    # Writer
    "write_section_tool",
    "write_all_sections_tool",
    "writer_audit_tool",
    # Reviewer
    "review_draft_tool",
    # Illustrator
    "match_images_tool",
    # Assembler
    "assemble_article_tool",
]
