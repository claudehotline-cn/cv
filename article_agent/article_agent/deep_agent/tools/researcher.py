"""Article Deep Agent Tools - Researcher Agent"""
from __future__ import annotations

import logging
import os
import json
import re
import glob
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from ...config.llm_runtime import build_chat_llm, extract_text_content
from ..utils.logging.tools_logging import log_performance, log_llm_response
from ..utils.artifacts import get_current_article_id, load_article_artifact, save_article_artifact
from ...config.config import get_article_dir, settings
from .prompts import RESEARCHER_SECTION_SYSTEM_PROMPT, RESEARCHER_SECTION_USER_PROMPT

_LOGGER = logging.getLogger("article_agent.deep_agent.tools.researcher")

@tool
def research_section_tool(
    section_id: str,
    section_title: str,
    keywords: List[str],
    sources_text: str,
    available_images: List[Dict[str, Any]] = None,
    required_evidence: List[Dict[str, Any]] = None,  # 新增：从 section_plan 获取
) -> Dict[str, Any]:
    """为指定章节整理资料笔记（结构化 JSON 输出）。
    
    Args:
        section_id: 章节 ID
        section_title: 章节标题
        keywords: 关键词列表
        sources_text: 素材文本（已合并）
        available_images: 可用图片列表
        required_evidence: 所需证据类型列表 (来自 section_plan.json)
        
    Returns:
        结构化的 SectionNotes 字典，包含 evidence 证据链
    """
    
    _LOGGER.info(f"research_section_tool called for section: {section_id}")
    
    keywords_str = ', '.join(keywords) if keywords else '无特定关键词'
    
    # 格式化 required_evidence 为字符串
    if required_evidence:
        evidence_str = ", ".join([f"{e.get('type', 'fact')}(最少{e.get('min', 1)}条)" for e in required_evidence])
    else:
        evidence_str = "fact(最少2条), quote(最少1条)"  # 默认值
    
    system_prompt = RESEARCHER_SECTION_SYSTEM_PROMPT.format(
        section_title=section_title, 
        keywords_str=keywords_str,
        section_id=section_id,
        required_evidence=evidence_str
    )

    user_prompt = RESEARCHER_SECTION_USER_PROMPT.format(
        sources_text_preview=sources_text[:80000], 
        section_title=section_title,
        section_id=section_id
    )

    try:
        with log_performance("research_section", section_id=section_id):
            llm = build_chat_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            
            _LOGGER.info(f"[DEBUG_CTX] research_section prompt size: system_len={len(system_prompt)}, user_len={len(user_prompt)}")
            
            input_chars = len(system_prompt) + len(user_prompt)
            response = llm.invoke(messages)
            
            # 记录 LLM 响应详情
            log_llm_response("research_section", response, input_chars=input_chars)
            
            raw_content = extract_text_content(response)
        
        # 尝试解析 JSON
        structured_note = None
        try:
            # 提取 JSON 块（处理可能的 markdown 代码块包裹）
            import re
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', raw_content)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 尝试直接解析
                json_str = raw_content.strip()
            
            structured_note = json.loads(json_str)
            _LOGGER.info(f"Parsed structured note for {section_id}: {len(structured_note.get('evidence', []))} evidence items")
        except json.JSONDecodeError as je:
            _LOGGER.warning(f"Failed to parse JSON for {section_id}, falling back to text: {je}")
            # Fallback: 保留原始文本作为 notes
            structured_note = {
                "section_id": section_id,
                "bullet_points": [],
                "evidence": [],
                "notes": raw_content  # 兼容旧格式
            }
        
        # 匹配相关图片
        relevant_images = []
        if available_images:
            for img in available_images[:5]:  # 最多 5 张
                alt = img.get("alt", "")
                if any(kw.lower() in alt.lower() for kw in keywords):
                    relevant_images.append(img)
        
        # 合并结果
        result = {
            "section_id": section_id,
            "bullet_points": structured_note.get("bullet_points", []),
            "evidence": structured_note.get("evidence", []),
            "notes": structured_note.get("notes", ""),  # 兼容旧格式
            "relevant_images": relevant_images,
        }
        
        _LOGGER.info(f"research_section_tool success: {len(result.get('evidence', []))} evidence, {len(relevant_images)} images")
        return result
        
    except Exception as exc:
        _LOGGER.error(f"research_section_tool failed: {exc}")
        return {
            "section_id": section_id,
            "bullet_points": [],
            "evidence": [],
            "notes": f"资料整理失败: {exc}",
            "relevant_images": [],
        }


@tool
def research_all_sections_tool(
    outline: Dict[str, Any],
    sources: List[Dict[str, Any]] = None,
    article_id: str = "",  # 新增：接收 article_id
) -> Dict[str, Any]:
    """为所有章节整理资料笔记。
    
    Args:
        outline: 文章大纲
        sources: (可选) 自动从 sources.json 读取
        article_id: 文章 ID (必须传入，用于定位文件)
        
    Returns:
        ResearcherOutput 字典
    """
    
    # 优先加载 Persistent Outline (此时 outline 参数可能是空的)
    article_id = get_current_article_id(article_id)
    _LOGGER.info(f"[DEBUG] research_all_sections_tool: article_id = '{article_id}'")
    
    loaded_outline = load_article_artifact(article_id, "outline.json")
    if loaded_outline:
         _LOGGER.info(f"Loaded outline from artifacts")
    else:
        _LOGGER.warning("[DEBUG] research_all_sections_tool: outline artifact not found or empty")

    if loaded_outline:
        outline = loaded_outline
    elif not outline or not outline.get("sections"):
        _LOGGER.warning("No outline provided and no outline file found!")
        return {"section_notes": [], "error": "Missing outline"}
    
    # NEW: 加载 section_plan.json 以获取 required_evidence
    section_plan = load_article_artifact(article_id, "section_plan.json")
    section_plan_map = {}
    if section_plan and section_plan.get("sections"):
        for sp in section_plan.get("sections", []):
            section_plan_map[sp.get("section_id", "")] = sp
        _LOGGER.info(f"Loaded section_plan with {len(section_plan_map)} sections")
    else:
        _LOGGER.info("No section_plan.json found, proceeding without evidence requirements")
    
    _LOGGER.info(f"research_all_sections_tool called. Outline sections: {len(outline.get('sections', []))}")

    # NEW: Try loading Chunks (Docling artifact)
    article_dir = get_article_dir(article_id)
    corpus_pattern = os.path.join(article_dir, "corpus", "*", "chunks.jsonl")
    chunk_files = glob.glob(corpus_pattern)
    
    all_text = ""
    all_images = []
    
    if chunk_files:
        _LOGGER.info(f"Found {len(chunk_files)} chunk files in corpus.")
        chunks_text_list = []
        for cf in chunk_files:
            try:
                with open(cf, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip(): continue
                        try:
                            c = json.loads(line)
                            cid = c.get("chunk_id", "unknown")
                            content = c.get("content", "")
                            # Format: [Chunk ID: doc_x_c1] content...
                            chunks_text_list.append(f"[Chunk ID: {cid}]\n{content}")
                        except: pass
            except Exception as e:
                _LOGGER.warning(f"Error reading chunks {cf}: {e}")
        all_text = "\n\n".join(chunks_text_list)
        _LOGGER.info(f"Loaded {len(chunks_text_list)} chunks from corpus.")
    else:
        # Fallback: strict legacy mode
        _LOGGER.info("No chunks.jsonl found, trying sources.json")
        loaded_sources_data = load_article_artifact(article_id, "sources.json")
        loaded_sources = loaded_sources_data.get("sources", []) if loaded_sources_data else []
        
        if loaded_sources:
             all_text = "\n\n".join([
                f"【来源: {s.get('title', s.get('url', 'unknown'))}】\n{s.get('full_text', s.get('text_preview', ''))}"
                for s in loaded_sources
            ])
             for s in loaded_sources:
                 all_images.extend(s.get("images", []))
        else:
            _LOGGER.warning("No chunks AND no sources.json found!")
            return {"error": "No content found/ingested."}

    section_notes = []
    
    # Parallel processing
    sections = outline.get("sections", [])
    max_workers = 1  # Standard sequential
    
    _LOGGER.info(f"[Parallel] Starting Native LangChain batch research with max_concurrency={max_workers} for {len(sections)} sections")
    
    batch_inputs = []
    for idx, sec in enumerate(sections):
        section_id = sec.get("id") or sec.get("section_id") or f"sec_{idx + 1}"
        section_title = sec.get("title") or sec.get("heading") or f"章节 {idx + 1}"
        
        # 从 section_plan_map 获取 required_evidence
        plan_info = section_plan_map.get(section_id, {})
        required_evidence = plan_info.get("required_evidence", [])
        
        batch_inputs.append({
            "section_id": section_id,
            "section_title": section_title,
            "keywords": sec.get("keywords", []) or plan_info.get("keywords", []),
            "sources_text": all_text,
            "available_images": all_images,
            "required_evidence": required_evidence,
        })
    
    try:
        section_notes = research_section_tool.batch(
            batch_inputs,
            config=RunnableConfig(max_concurrency=max_workers)
        )
    except Exception as e:
        _LOGGER.error(f"[Parallel] Batch research failed: {e}")
        section_notes = []
        for inp in batch_inputs:
             section_notes.append({
                 "section_id": inp["section_id"], 
                 "notes": f"批量研究失败: {e}", 
                 "relevant_images": []
             })
    
    _LOGGER.info(f"[Parallel] All {len(section_notes)} sections researched")
    
    full_output = {
        "article_id": article_id,
        "section_notes": section_notes,
        "source_summaries": {}, 
    }
    
    try:
        if article_id:
            notes_file = save_article_artifact(article_id, "research_notes.json", full_output)
            full_output["notes_file"] = notes_file
            _LOGGER.info(f"Research notes saved to: {notes_file}")
    except Exception as exc:
        _LOGGER.warning(f"Failed to save research notes: {exc}")
    
    notes_file_path = full_output.get("notes_file", "")
    
    return {
        "status": "SUCCESS",
        "message": f"研究完成！已为 {len(section_notes)} 个章节整理好笔记并保存到文件。请立即调用 writer_agent 开始撰写文章。",
        "next_step": "writer_agent",
        "notes_file": notes_file_path,
        "total_sections": len(section_notes),
        "total_chars": sum(len(n.get("notes", "")) for n in section_notes),
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
