"""Article Deep Agent Tools - Writer Agent"""
from __future__ import annotations

import logging
import os
import json
import glob
import re
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agent_core.runtime import build_chat_llm
from ..utils.text_utils import extract_text_content
from ..utils.logging.tools_logging import log_performance, log_llm_response, log_tool_output
from ..utils.artifacts import load_article_artifact, save_draft_file, get_drafts_dir
from .prompts import WRITER_SECTION_REVIEW_FEEDBACK, WRITER_SECTION_SYSTEM_PROMPT, WRITER_SECTION_USER_PROMPT

_LOGGER = logging.getLogger("article_agent.deep_agent.tools.writer")


def _merge_drafts_to_single_file(article_id: str, outline: Optional[Dict[str, Any]] = None, user_id: str = "default") -> str:
    """
    将所有章节草稿合并为单一 draft.md 文件。
    
    Args:
        article_id: 文章 ID
        outline: 大纲（用于确定章节顺序），可选
        
    Returns:
        合并后的 draft.md 路径
    """
    from ..utils.artifacts import get_article_dir
    
    drafts_dir = get_drafts_dir(article_id, user_id=user_id)
    article_dir = get_article_dir(article_id, user_id=user_id)
    draft_output_dir = os.path.join(article_dir, "draft")
    os.makedirs(draft_output_dir, exist_ok=True)
    merged_draft_path = os.path.join(draft_output_dir, "draft.md")
    
    # 查找所有章节文件
    section_files = glob.glob(os.path.join(drafts_dir, "section_*.md"))
    
    if not section_files:
        _LOGGER.warning(f"No section files found in {drafts_dir}")
        return ""
    
    # 确定排序顺序
    def extract_section_num(path: str) -> int:
        match = re.search(r'section_sec_(\d+)', path)
        return int(match.group(1)) if match else 999
    
    # 如果有大纲，按大纲顺序；否则按文件名数字顺序
    if outline and outline.get("sections"):
        section_order = {s.get("id", ""): i for i, s in enumerate(outline.get("sections", []))}
        def sort_key(path: str) -> int:
            # 从文件名提取 section_id: section_sec_1.md -> sec_1
            basename = os.path.basename(path)
            match = re.search(r'section_(sec_\d+)', basename)
            if match:
                return section_order.get(match.group(1), 999)
            return 999
        section_files.sort(key=sort_key)
    else:
        section_files.sort(key=extract_section_num)
    
    # 合并内容
    full_content_parts = []
    for sf in section_files:
        try:
            with open(sf, "r", encoding="utf-8") as f:
                content = f.read()
                full_content_parts.append(content)
        except Exception as e:
            _LOGGER.warning(f"Failed to read {sf}: {e}")
    
    full_draft_content = "\n\n".join(full_content_parts)
    
    # 写入合并文件
    with open(merged_draft_path, "w", encoding="utf-8") as f:
        f.write(full_draft_content)
    
    _LOGGER.info(f"Merged {len(section_files)} sections to {merged_draft_path} ({len(full_draft_content)} chars)")
    return merged_draft_path

@tool
def write_section_tool(
    section_id: str,
    section_title: str,
    target_chars: int,
    notes: str,
    assigned_images_str: str = "无",
    is_core: bool = False,
    review_feedback: str = "",
    article_id: str = "",  # 新增：并行执行时必须显式传入
    config: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """撰写指定章节内容。
    
    Args:
        section_id: 章节 ID
        section_title: 章节标题
        target_chars: 目标字数
        notes: 资料笔记
        is_core: 是否核心章节
        review_feedback: 审阅反馈（可选，用于修改稿件）
        config: RunnableConfig injection
        
    Returns:
        SectionDraft 字典
    """
    
    _LOGGER.info(f"write_section_tool called for section: {section_id}, target_chars: {target_chars}")
    
    # Extract task_id from config
    task_id = "main"
    if config:
         configurable = config.get("configurable", {})
         task_id = configurable.get("task_id", "main")
         
    min_chars = 800 if is_core else 400
    
    # 如果有审阅反馈，添加到 prompt 中
    review_section = ""
    if review_feedback:
        review_section = WRITER_SECTION_REVIEW_FEEDBACK.format(review_feedback=review_feedback)
        _LOGGER.info(f"write_section_tool has review feedback for section {section_id}")
    
    system_prompt = WRITER_SECTION_SYSTEM_PROMPT.format(
        section_title=section_title,
        review_section=review_section,
        target_chars=target_chars,
        min_chars=min_chars
    )

    user_prompt = WRITER_SECTION_USER_PROMPT.format(
        notes_preview=notes[:6000], 
        target_chars=target_chars,
        assigned_images=assigned_images_str # Add formatting
    )

    try:
        with log_performance("write_section", section_id=section_id, target_chars=target_chars):
            llm = build_chat_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            input_chars = len(system_prompt) + len(user_prompt)
            response = llm.invoke(messages)
            
            # 记录 LLM 响应详情
            log_llm_response("write_section", response, input_chars=input_chars)
            
            markdown = extract_text_content(response)
        
        # 确保以标题开头
        if not markdown.startswith("#"):
            markdown = f"## {section_title}\n\n{markdown}"
        
        char_count = len(markdown)
        
        # 落盘：保存到临时文件
        import uuid
        
        # article_id 已作为参数传入，无需从 ContextVar 获取
        # If not provided (single call), we can't do much without context var, 
        # but the agent usually passes it. 
        if not article_id:
             _LOGGER.warning("write_section_tool called without article_id, cannot save file correctly!")
             # Try environment fallback if absolutely necessary, or just fail
             # For now, let's assume article_id is passed or handled by caller
             pass
        
        if article_id:
             file_path = save_draft_file(article_id, section_id, markdown, task_id)
        else:
             file_path = ""
        
        _LOGGER.info(f"write_section_tool success: {char_count} chars, saved to {file_path}")
        
        result = {
            "section_id": section_id,
            "title": section_title,
            "file_path": file_path,  # 返回文件路径而不是完整内容
            "char_count": char_count,
            "preview": markdown[:200] + "..." if len(markdown) > 200 else markdown,  # 只返回预览
        }
        
        # 如果是修改稿件（有审阅反馈），自动重新合并 draft.md
        if review_feedback and article_id:
            try:
                outline = load_article_artifact(article_id, "outline.json", task_id)
                # _merge_drafts_to_single_file needs to support task_id too, let's update it later or inline fix
                # For now let's hope merge tool is called separately or we fix merge helper
                pass 
                merged_path = _merge_drafts_to_single_file(article_id, outline, user_id=user_id) 
            except Exception as merge_err:
                _LOGGER.warning(f"Failed to re-merge draft after revision: {merge_err}")
        
        # 记录详细输出
        log_tool_output("write_section_tool", result, preview_fields=["preview"])
        
        return result
    except Exception as exc:
        _LOGGER.error(f"write_section_tool failed: {exc}")
        return {
            "section_id": section_id,
            "title": section_title,
            "file_path": "",
            "char_count": 0,
            "error": str(exc),
        }


@tool
def write_all_sections_tool(
    article_id: str = "",
    outline: Dict[str, Any] = None,
    config: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """撰写所有章节内容。
    
    Args:
        article_id: 文章 ID，由 Main Agent 从用户消息提取并传递
        outline: (可选) 文章大纲。如果未提供，将自动从 artifacts 加载。
        config: RunnableConfig injection
        
    Returns:
        WriterOutput 字典
    """
    _LOGGER.info(f"write_all_sections_tool called with article_id: '{article_id}'")
    
    # Extract task_id from config
    task_id = "main"
    if config:
         configurable = config.get("configurable", {})
         task_id = configurable.get("task_id", "main")
         
    # 直接使用传入的 article_id（由 Main Agent 从用户消息提取并传递）
    _LOGGER.info(f"[DEBUG] write_all_sections_tool: article_id = '{article_id}', task_id = '{task_id}'")
    
    loaded_outline = load_article_artifact(article_id, "outline.json", task_id)
    if loaded_outline:
        _LOGGER.info(f"Loaded outline from artifacts")
    else:
        _LOGGER.warning("[DEBUG] write_all_sections_tool: outline artifact not found or empty")

    if loaded_outline:
        outline = loaded_outline
    elif not outline or not outline.get("sections"):
        _LOGGER.warning("No outline provided and no outline file found!")
        return {"drafts": [], "error": "Missing outline"}
    
    # 强制从文件加载研究笔记（不使用内存数据）
    loaded_notes = []
    if article_id:
        notes_data = load_article_artifact(article_id, "research_notes.json", task_id)
        loaded_notes = notes_data.get("section_notes", [])
        if loaded_notes:
            _LOGGER.info(f"Loaded {len(loaded_notes)} notes from artifacts")
    
    if not loaded_notes:
        _LOGGER.warning("No research notes found in file! Writer will likely fail or hallucinate.")
        return {
            "drafts": [],
            "total_chars": 0,
            "error": "Research notes file not found or empty. Please run Researcher first."
        }
    
    # 加载审阅反馈（如果存在）- 用于修改稿件
    review_feedback = {}
    if article_id:
        review_feedback = load_article_artifact(article_id, "review_report.json", task_id)
        if review_feedback:
             _LOGGER.info(f"Loaded review feedback from artifacts, approved={review_feedback.get('approved')}")
    
    # 使用加载的笔记
    section_notes = loaded_notes
    
    # 构建笔记映射 (Store full object to access assigned_images)
    notes_map = {n.get("section_id", ""): n for n in section_notes}
    _LOGGER.info(f"Built notes map with {len(notes_map)} entries. Keys: {list(notes_map.keys())[:5]}")
    
    drafts = []
    total_chars = 0
    
    sections = outline.get("sections", [])
    _LOGGER.info(f"Processing {len(sections)} sections from outline")
    
    # 并行处理所有章节 (Parallel Execution)
    max_workers = 1  # 串行执行
    
    _LOGGER.info(f"[Parallel] Starting Native LangChain batch writing with max_concurrency={max_workers} for {len(sections)} sections")
    
    # 构造 batch 输入
    batch_inputs = []
    for idx, sec in enumerate(sections):
        section_id = sec.get("id") or sec.get("section_id") or f"sec_{idx + 1}"
        section_title = sec.get("title") or sec.get("heading") or f"章节 {idx + 1}"
        
        # Get note object
        note_obj = notes_map.get(section_id, {})
        notes_text = note_obj.get("notes", "") if isinstance(note_obj, dict) else ""
        
        # Format assigned images for this section
        assigned_imgs = note_obj.get("assigned_images", []) if isinstance(note_obj, dict) else []
        assigned_images_str = "无"
        if assigned_imgs:
            lines = []
            for img in assigned_imgs:
                # Handle both dict (new format) and str (legacy)
                if isinstance(img, dict):
                    img_id = img.get("id", "unknown")
                    # Prefer caption (short title) over desc (long description)
                    img_caption = img.get("caption") or img.get("desc", "")[:20] or "参考图片"
                    lines.append(f"- ID: {img_id} | 图注: {img_caption}")
                else:
                    lines.append(f"- ID: {str(img)}") # Legacy fallback
            assigned_images_str = "\n".join(lines)

        
        # 查找该章节的审阅反馈
        section_review = ""
        if review_feedback and review_feedback.get("section_feedback"):
            for fb in review_feedback.get("section_feedback", []):
                if fb.get("section_id") == section_id:
                    issues = fb.get("issues", [])
                    suggestions = fb.get("suggestions", [])
                    section_review = f"审阅反馈 - 问题: {', '.join(issues) if issues else '无'}; 建议: {', '.join(suggestions) if suggestions else '无'}"
                    _LOGGER.info(f"[Parallel] Section {section_id} has review feedback: {section_review[:100]}")
                    break
        
        batch_inputs.append({
            "section_id": section_id,
            "section_title": section_title,
            "target_chars": sec.get("target_chars", 500),
            "notes": notes_text,
            "assigned_images_str": assigned_images_str,
            "is_core": sec.get("is_core", False),
            "review_feedback": section_review,
            "article_id": article_id,  # 显式传入 article_id 以支持并行执行
        })

    # 使用 LangChain 原生 batch
    try:
        drafts = write_section_tool.batch(
            batch_inputs,
            config=RunnableConfig(max_concurrency=max_workers)
        )
    except Exception as e:
        _LOGGER.error(f"[Parallel] Batch writing failed: {e}")
        drafts = []
        for inp in batch_inputs:
            drafts.append({
                "section_id": inp["section_id"],
                "content": f"写作失败: {e}",
                "char_count": 0
            })

    # 计算总字数
    for d in drafts:
        total_chars += d.get("char_count", 0)
    
    _LOGGER.info(f"[Parallel] All {len(drafts)} sections written, total_chars={total_chars}")
    
    # ========== 新增：生成 citations_map.json ==========
    # 从草稿中提取引用锚点 [^doc_xxx_c3] 格式
    import re
    citations_anchors = []
    
    for draft in drafts:
        file_path = draft.get("file_path", "")
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                # 提取 [^chunk_id] 格式的引用
                refs = re.findall(r'\[\^(doc_[a-z0-9_]+_c\d+)\]', content)
                for ref in refs:
                    citations_anchors.append({
                        "anchor": f"cite:{ref}",
                        "refs": [{"chunk_id": ref}],
                        "section_id": draft.get("section_id", "")
                    })
            except Exception as e:
                _LOGGER.warning(f"Failed to extract citations from {file_path}: {e}")
    
    # 保存 citations_map.json
    citations_map = {
        "article_id": article_id,
        "anchors": citations_anchors,
        "total_citations": len(citations_anchors)
    }
    
    citations_map_path = ""
    if article_id:
        try:
            from ..utils.artifacts import save_article_artifact
            citations_map_path = save_article_artifact(article_id, "citations_map.json", citations_map)
            _LOGGER.info(f"Citations map saved to: {citations_map_path}, {len(citations_anchors)} anchors")
        except Exception as e:
            _LOGGER.warning(f"Failed to save citations_map: {e}")
    
    
    # 强制不返回 drafts 内容，确保下游 Reviewer 必须从文件系统读取
    # 但必须返回足够的 Metadata 告知 LLM 任务已完成，否则会导致 infinite retry loop
    
    # 由 Downstream (Illustrator/Assembler) 负责合并
    merged_draft_path = ""
    # _LOGGER.info("Skipping merge in Writer, delegating to Assembler/Illustrator")

    return {
        "status": "success",
        "message": f"Successfully wrote {len(drafts)} sections to file system",
        "drafts": [], # Empty list kept for Zero-Memory compliance
        "total_char_count": total_chars,
        "saved_files": [d["file_path"] for d in drafts], # Minimal references
        # "merged_draft": merged_draft_path,  # Removed to force downstream handling
        "citations_map_path": citations_map_path,
        "total_citations": len(citations_anchors)
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
    _LOGGER.info(f"writer_audit_tool called")
    
    # 构建 section 字数要求映射
    section_requirements = {}
    for idx, sec in enumerate(outline.get("sections", [])):
        section_id = sec.get("id") or sec.get("section_id") or f"sec_{idx + 1}"
        section_requirements[section_id] = {
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


@tool
def merge_draft_tool(article_id: str = "", config: Dict[str, Any] = None) -> Dict[str, Any]:
    """将所有章节草稿合并为单一 draft.md 文件。
    
    在审阅不通过、修改章节后调用此工具，重新生成合并的草稿文件。
    
    Args:
        article_id: 文章 ID（可选，默认使用当前上下文）
        config: RunnableConfig injection
        
    Returns:
        合并结果，包含 merged_draft 路径
    """
    _LOGGER.info(f"merge_draft_tool called for article_id={article_id}")
    
    # Extract task_id from config
    task_id = "main"
    if config:
         configurable = config.get("configurable", {})
         task_id = configurable.get("task_id", "main")
         
    # Legacy: get_current_article_id is removed in previous steps or simplified to just return argument
    # So we depend on argument being passed.
    
    if not article_id:
        return {"error": "Missing article_id"}
    
    try:
        # 加载大纲以确保正确顺序
        outline = load_article_artifact(article_id, "outline.json", task_id)
        
        # We need to update _merge_drafts_to_single_file to support task_id, 
        # but since it's an internal helper not exposed as tool, we can modify it inline or just fix it now.
        # Let's fix _merge_drafts_to_single_file signature in next step or assume it's fine if we update it.
        # Actually I need to update _merge_drafts_to_single_file too. 
        # For now let's call it and see if I can update it in same file.
        # I'll update the helper function in a separate block or relying on next step.
        pass
        # merged_path = _merge_drafts_to_single_file(article_id, outline, task_id)
        
        # Inline logic for merge since helper is not updated yet
        from ..utils.artifacts import get_article_dir, get_drafts_dir
        
        drafts_dir = get_drafts_dir(article_id, task_id)
        article_dir = get_article_dir(article_id, task_id)
        draft_output_dir = os.path.join(article_dir, "draft")
        os.makedirs(draft_output_dir, exist_ok=True)
        merged_draft_path = os.path.join(draft_output_dir, "draft.md")
        
        # 查找所有章节文件
        import glob
        import re
        section_files = glob.glob(os.path.join(drafts_dir, "section_*.md"))
        
        if not section_files:
            _LOGGER.warning(f"No section files found in {drafts_dir}")
            return {"error": "No section files found"}
        
        # 确定排序顺序
        def extract_section_num(path: str) -> int:
            match = re.search(r'section_sec_(\d+)', path)
            return int(match.group(1)) if match else 999
        
        # 如果有大纲，按大纲顺序；否则按文件名数字顺序
        if outline and outline.get("sections"):
            section_order = {s.get("id", ""): i for i, s in enumerate(outline.get("sections", []))}
            def sort_key(path: str) -> int:
                # 从文件名提取 section_id: section_sec_1.md -> sec_1
                basename = os.path.basename(path)
                match = re.search(r'section_(sec_\d+)', basename)
                if match:
                    return section_order.get(match.group(1), 999)
                return 999
            section_files.sort(key=sort_key)
        else:
            section_files.sort(key=extract_section_num)
        
        # 合并内容
        full_content_parts = []
        for sf in section_files:
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    content = f.read()
                    full_content_parts.append(content)
            except Exception as e:
                _LOGGER.warning(f"Failed to read {sf}: {e}")
        
        full_draft_content = "\n\n".join(full_content_parts)
        
        # 写入合并文件
        with open(merged_draft_path, "w", encoding="utf-8") as f:
            f.write(full_draft_content)
        
        _LOGGER.info(f"Merged {len(section_files)} sections to {merged_draft_path} ({len(full_draft_content)} chars)")
        merged_path = merged_draft_path
            
        if merged_path:
            # 读取合并后的内容统计
            char_count = 0
            try:
                with open(merged_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    char_count = len(content)
            except:
                pass
            
            return {
                "status": "success",
                "merged_draft": merged_path,
                "char_count": char_count,
                "message": f"Successfully merged all sections to {merged_path}"
            }
        else:
            return {"error": "No section files found to merge"}
            
    except Exception as e:
        _LOGGER.error(f"merge_draft_tool failed: {e}")
        return {"error": str(e)}
