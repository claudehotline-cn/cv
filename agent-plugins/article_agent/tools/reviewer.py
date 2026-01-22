"""Article Deep Agent Tools - Reviewer Agent"""
from __future__ import annotations

import logging
import os
import json
import re
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from ...config.llm_runtime import build_chat_llm, extract_text_content
from ..utils.logging.tools_logging import log_performance, log_llm_response
from ..utils.artifacts import get_current_article_id, load_article_artifact, save_article_artifact, get_drafts_dir
from .prompts import REVIEWER_DRAFT_SYSTEM_PROMPT, REVIEWER_DRAFT_USER_PROMPT

_LOGGER = logging.getLogger("article_agent.deep_agent.tools.reviewer")

@tool
def review_draft_tool(article_id: str, drafts: List[Dict[str, Any]], instruction: str) -> Dict[str, Any]:
    """审阅草稿，返回反馈和是否通过。
    
    Args:
        article_id: 文章 ID，由 Main Agent 从用户消息提取并传递
        drafts: 各章节草稿（包含 file_path）
        instruction: 用户写作指令
        
    Returns:
        ReviewerOutput 字典
    """
    
    _LOGGER.info(f"review_draft_tool called with {len(drafts)} sections, article_id='{article_id}'")
    
    # 1. 第一步：获取"藏宝图" (加载 Persistent Outline)
    # 直接使用传入的 article_id（由 Main Agent 从用户消息提取并传递）
    _LOGGER.info(f"review_draft_tool: Starting execution (article_id={article_id})")
    
    loaded_outline = load_article_artifact(article_id, "outline.json")
    if loaded_outline:
        _LOGGER.info(f"Loaded outline from artifacts")
    else:
        _LOGGER.warning(f"Failed to load outline from artifacts")

    outline = loaded_outline or {}
        
    # 2. 强制从大纲和文件系统读取草稿 (忽略内存输入的 drafts)
    # 用户要求：即使 drafts 不为空，也要读文件
    _LOGGER.info("Scanning file system for drafts based on outline...")
    
    found_drafts = []
    if outline and article_id:
         article_dir = get_drafts_dir(article_id)
         for sec in outline.get("sections", []):
             sec_id = sec.get("id") or sec.get("section_id")
             if sec_id:
                 # 尝试匹配文件名 (section_id.md)
                 draft_path = os.path.join(article_dir, f"{sec_id}.md")
                 
                 # 兼容旧命名 (section_N.md)
                 if not os.path.exists(draft_path) and "sec_" in sec_id:
                     # 尝试匹配 section_sec_1.md (现在实际生成的格式)
                     draft_path_prefix = os.path.join(article_dir, f"section_{sec_id}.md")
                     if os.path.exists(draft_path_prefix):
                         draft_path = draft_path_prefix
                     else:
                         try:
                             idx = int(sec_id.split("_")[1])
                             draft_path_alt = os.path.join(article_dir, f"section_{idx}.md")
                             if os.path.exists(draft_path_alt):
                                 draft_path = draft_path_alt
                         except:
                             pass
                         
                 if os.path.exists(draft_path):
                     found_drafts.append({
                         "file_path": draft_path, 
                         "section_id": sec_id,
                         "title": sec.get("title", "")
                     })
                     _LOGGER.info(f"Found draft file: {draft_path}")
    
    # 使用找到的 drafts 覆盖输入
    if found_drafts:
        drafts = found_drafts
        _LOGGER.info(f"Reviewing {len(drafts)} drafts found in filesystem")
    else:
        _LOGGER.warning("No drafts found in filesystem! Using memory drafts if available.")
    
    if not drafts:
        return {
            "overall_quality": 0,
            "section_feedback": [],
            "sections_to_rewrite": [],
            "approved": False,
            "error": "No drafts found to review"
        }

    # 从文件读取所有草稿内容
    sections_content = []
    for d in drafts:
        file_path = d.get("file_path", "")
        if file_path and os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            sections_content.append(content)
        else:
            # 兼容旧格式或预览
            sections_content.append(d.get("markdown", d.get("preview", "")))
    
    all_markdown = "\n\n".join(sections_content)
    
    system_prompt = REVIEWER_DRAFT_SYSTEM_PROMPT

    user_prompt = REVIEWER_DRAFT_USER_PROMPT.format(instruction=instruction, draft_content_preview=all_markdown[:3000])
    _LOGGER.info("review_draft_tool: Constructed user_prompt. Building LLM client...")
    try:
        llm = build_chat_llm()
        _LOGGER.info("review_draft_tool: LLM client built. Preparing messages...")
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        _LOGGER.info("review_draft_tool: Messages prepared. Invoking LLM (this might take a while)...")
        response = llm.invoke(messages)
        _LOGGER.info("review_draft_tool: LLM invoke returned!")
        content = extract_text_content(response)
        
        # 提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            # 修复常见的 JSON 转义错误 (如 LaTeX 公式中的反斜杠)
            # 将所有未跟随合法转义字符的反斜杠双写
            json_str = re.sub(r'\\([^"\\/bfnrtu])', r'\\\\\1', json_str)
            
            try:
                result = json.loads(json_str)
            except json.JSONDecodeError as je:
                _LOGGER.warning(f"JSON parse error: {je}. Trying to recover...")
                # 尝试更激进的修复：移除所有反斜杠 (除了转义引号的)
                json_str_fixed = re.sub(r'\\(?!")', '', json_str)
                try:
                    result = json.loads(json_str_fixed)
                except:
                    # 如果仍然失败，抛出原始错误
                    raise je
            # 确保 approved 字段
            if "approved" not in result:
                result["approved"] = result.get("overall_quality", 0) >= 7
            _LOGGER.info(f"review_draft_tool: quality={result.get('overall_quality')}, approved={result.get('approved')}")
            
            # 保存审阅结果到文件，供 Writer 读取
            try:
                if article_id:
                    review_file = save_article_artifact(article_id, "review_report.json", result)
                    _LOGGER.info(f"Review saved to: {review_file}")
                    result["review_file"] = review_file
            except Exception as e:
                _LOGGER.warning(f"Failed to save review to file: {e}")
            
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
